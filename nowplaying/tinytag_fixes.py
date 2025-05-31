#!/usr/bin/env python3
"""
Monkey patches for tinytag to fix M4A multi-value field parsing.

This module applies a fix to tinytag 2.1.1 to properly handle multi-value
fields in M4A files. The issue is that M4A custom field atoms (----) can
contain multiple 'data' atoms for the same field, but tinytag only processes
the last one.
"""

import logging
from io import BytesIO
from struct import unpack

import tinytag.tinytag


def _check_tinytag_compatibility():
    """Check if the current tinytag version is compatible with our patches."""
    # Note: tinytag 2.1.1 doesn't expose __version__ in code, so we check for required methods
    try:
        # Verify the required internal structure exists for our patches
        if not hasattr(tinytag.tinytag, '_MP4'):
            logging.error("tinytag._MP4 class not found. Incompatible tinytag version.")
            return False
        if not hasattr(tinytag.tinytag._MP4, '_parse_custom_field'):  # pylint: disable=protected-access
            logging.error("tinytag._MP4._parse_custom_field method not found. "
                         "Incompatible tinytag version.")
            return False
        if not hasattr(tinytag.tinytag.TinyTag, '_set_field'):
            logging.error("tinytag.TinyTag._set_field method not found. "
                         "Incompatible tinytag version.")
            return False
        return True
    except AttributeError as exc:
        logging.error("tinytag compatibility check failed: %s", exc)
        return False


def _create_patched_methods():
    """Create the patched methods for tinytag M4A multi-value handling."""
    # Store original methods
    _original_parse_custom_field = tinytag.tinytag._MP4._parse_custom_field  # pylint: disable=protected-access
    _original_set_field = tinytag.tinytag.TinyTag._set_field  # pylint: disable=protected-access

    @classmethod
    def _parse_custom_field_fixed(cls, data: bytes) -> dict[str, int | str | bytes | None]:
        """
        Fixed version of _parse_custom_field that handles multiple data atoms.

        The original version only keeps the last data atom when multiple exist.
        This version collects all data atoms for a field and returns them as a list.
        """
        file_handle = BytesIO(data)
        header_len = 8
        field_name = None
        data_atoms = []  # Collect ALL data atoms
        atom_header = file_handle.read(header_len)

        while len(atom_header) == header_len:
            atom_size = unpack('>I', atom_header[:4])[0] - header_len
            atom_type = atom_header[4:]

            if atom_type == b'name':
                atom_value = file_handle.read(atom_size)[4:].lower()
                field_name = atom_value.decode('utf-8', 'replace')
                # pylint: disable=protected-access
                field_name = cls._CUSTOM_FIELD_NAME_MAPPING.get(  # pylint: disable=no-member
                    field_name, tinytag.tinytag.TinyTag._OTHER_PREFIX + field_name)  # pylint: disable=protected-access
            elif atom_type == b'data':
                data_atom = file_handle.read(atom_size)
                data_atoms.append(data_atom)
            else:
                file_handle.seek(atom_size, 1)  # SEEK_CUR
            atom_header = file_handle.read(header_len)  # read next atom

        if not data_atoms or field_name is None:
            return {}

        # Process ALL data atoms for this field
        values = []
        for data_atom in data_atoms:
            if len(data_atom) < 8:
                continue
            parser = cls._data_parser(field_name)  # pylint: disable=protected-access,no-member
            atom_result = parser(data_atom)
            if field_name in atom_result and atom_result[field_name]:
                values.append(atom_result[field_name])

        if not values:
            return {}
        # Return the list - tinytag's _set_field will handle it properly for other.* fields
        return {field_name: values}

    # Also patch _set_field to handle list values properly
    _original_set_field = tinytag.tinytag.TinyTag._set_field  # pylint: disable=protected-access

    def _set_field_fixed(self,
                         fieldname: str,
                         value: str | float | list,
                         check_conflict: bool = True) -> None:
        """
        Fixed version of _set_field that properly handles list values for other.* fields.
        """
        if fieldname.startswith(self._OTHER_PREFIX):  # pylint: disable=protected-access
            fieldname = fieldname[len(self._OTHER_PREFIX):]  # pylint: disable=protected-access
            if check_conflict and fieldname in self.__dict__:
                fieldname = '_' + fieldname

            # If value is a list, set it directly (for multi-value fields)
            if isinstance(value, list):
                self.other[fieldname] = value
                return

            # Original behavior for non-list values
            other_values = self.other.get(fieldname, [])
            if not isinstance(value, str) or value in other_values:
                return
            other_values.append(value)
            self.other[fieldname] = other_values
            return

        # For non-other fields, use original behavior but handle lists
        if isinstance(value, list):
            # For regular fields, just take the first value
            value = value[0] if value else ''

        _original_set_field(self, fieldname, value, check_conflict)

    return _parse_custom_field_fixed, _set_field_fixed


def apply_tinytag_patches():
    """
    Encapsulates monkey patching of TinyTag internals to minimize maintenance risk.
    Call this function once at application startup.

    This function applies patches to fix M4A multi-value field parsing in tinytag 2.1.1.
    The patches are only applied if the exact expected version is detected.
    """
    if not _check_tinytag_compatibility():
        return False

    try:
        # Create the patched methods
        parse_custom_field_fixed, set_field_fixed = _create_patched_methods()

        # Apply the patches to the protected APIs
        tinytag.tinytag._MP4._parse_custom_field = parse_custom_field_fixed  # pylint: disable=protected-access
        tinytag.tinytag.TinyTag._set_field = set_field_fixed  # pylint: disable=protected-access

        logging.debug("Successfully applied tinytag M4A multi-value custom field patches")
        return True

    except (AttributeError, ImportError) as exc:
        logging.error("Failed to apply tinytag patches: %s", exc)
        return False
