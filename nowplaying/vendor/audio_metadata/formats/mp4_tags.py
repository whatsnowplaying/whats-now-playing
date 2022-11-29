__all__ = [
	'MP4BooleanTag',
	'MP4Cover',
	'MP4CoverTag',
	'MP4FloatTag',
	'MP4Freeform',
	'MP4FreeformDecoders',
	'MP4FreeformTag',
	'MP4GenreTag',
	'MP4IntegerTag',
	'MP4NumberTag',
	'MP4TextTag',
	'MP4Tag',
	'MP4TagTypes',
]

import os
import struct

from attr import attrib, attrs
from ..tbm_utils import (
	AttrMapping,
	datareader,
)

from .tables import (
	ID3v1Genres,
	MP4AtomDataType,
	MP4CoverFormat,
)
from ..models import (
	Picture,
	Tag,
)
from ..utils import get_image_size


# https://developer.apple.com/library/archive/documentation/QuickTime/QTFF/Metadata/Metadata.html#//apple_ref/doc/uid/TP40000939-CH1-SW34
MP4FreeformDecoders = {
	MP4AtomDataType.IMPLICIT: lambda d: d,
	MP4AtomDataType.UTF8: lambda d: d.decode('utf-8', 'replace'),
	MP4AtomDataType.UTF16: lambda d: d.decode('utf-16', 'replace'),
	MP4AtomDataType.SJIS: lambda d: d.decode('s/jis', 'replace'),
	4: lambda d: d.decode('utf-8', 'replace'),
	5: lambda d: d.decode('utf-16', 'replace'),
	MP4AtomDataType.URL: lambda d: d.decode('utf-8', 'replace'),
	MP4AtomDataType.DURATION: lambda d: struct.unpack('>L', d)[0],
	MP4AtomDataType.DATETIME: lambda d: struct.unpack('>L', d)[0],  # TODO: Can be 32-bit or 64-bit.
	MP4AtomDataType.GIF: lambda d: d,
	MP4AtomDataType.JPEG: lambda d: d,
	MP4AtomDataType.PNG: lambda d: d,
	MP4AtomDataType.SIGNED_INT_BE: lambda d: struct.unpack('>b', d)[0],  # TODO: Can be 1, 2, 3, 4, 8 bytes.
	MP4AtomDataType.UNSIGNED_INT_BE: lambda d: struct.unpack('>B', d)[0],  # TODO: Can be 1, 2, 3, 4, 8 bytes.
	MP4AtomDataType.FLOAT_BE_32: lambda d: struct.unpack('>f', d)[0],
	MP4AtomDataType.FLOAT_BE_64: lambda d: struct.unpack('>d', d)[0],
	MP4AtomDataType.RIAA_PA: lambda d: struct.unpack('>d'. d)[0],
	MP4AtomDataType.UPC: lambda d: d,
	MP4AtomDataType.BMP: lambda d: d,
	28: lambda d: d,
	MP4AtomDataType.SIGNED_INT: lambda d: struct.unpack('b', d)[0],
	MP4AtomDataType.SIGNED_INT_BE_16: lambda d: struct.unpack('>h', d)[0],
	MP4AtomDataType.SIGNED_INT_BE_32: lambda d: struct.unpack('>i', d)[0],
	MP4AtomDataType.SIGNED_INT_BE_64: lambda d: struct.unpack('>q', d)[0],
	MP4AtomDataType.UNSIGNED_INT: lambda d: struct.unpack('B', d)[0],
	MP4AtomDataType.UNSIGNED_INT_BE_16: lambda d: struct.unpack('>H', d)[0],
	MP4AtomDataType.UNSIGNED_INT_BE_32: lambda d: struct.unpack('>I', d)[0],
	MP4AtomDataType.UNSIGNED_INT_BE_64: lambda d: struct.unpack('>Q', d)[0]
}


class MP4Cover(Picture):
	@datareader
	@classmethod
	def parse(cls, data):
		size = struct.unpack('>I', data.read(4))[0]
		data.seek(4, os.SEEK_CUR)
		format_ = MP4CoverFormat(struct.unpack('>I', data.read(4))[0])
		data.seek(4, os.SEEK_CUR)
		image_data = data.read(size - 16)
		width, height = get_image_size(image_data)

		return cls(format=format_, width=width, height=height, data=image_data)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4Freeform(AttrMapping):  # TODO: Other attributes.
	description = attrib()
	name = attrib()
	data_type = attrib(converter=MP4AtomDataType)
	value = attrib()


@attrs(
	repr=False,
	kw_only=True,
)
class MP4Tag(Tag):
	@datareader
	@classmethod
	def _parse_atom(cls, data, atom):
		atom_data = atom.read_data(data)
		position = 0

		while position < atom._size - 8:
			size, atom_name = struct.unpack('>I4s', atom_data[position : position + 8])
			if atom_name != b'data':
				raise Exception  # TODO

			version = atom_data[position + 8]
			flags = struct.unpack('>I', b'\x00' + atom_data[position + 9: position + 12])

			yield version, flags, atom_data[position + 16 : position + size]

			position += size

	@datareader
	@classmethod
	def parse(cls, data, atom):  # TODO: Move tag parsing logic into tag classes.
		if atom.type in MP4TagTypes:
			return MP4TagTypes[atom.type]._parse(data, atom)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4BooleanTag(MP4Tag):
	@datareader
	@classmethod
	def _parse(cls, data, atom):
		_, _, atom_data = next(cls._parse_atom(data, atom))
		if len(atom_data) != 1:
			raise Exception  # TODO

		return cls(
			name=atom.type,
			value=bool(atom_data[0]),
		)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4CoverTag(MP4Tag):
	@datareader
	@classmethod
	def _parse(cls, data, atom):
		atom_data = atom.read_data(data)

		covers = []
		remaining = atom_data
		while remaining:
			size, name = struct.unpack('>I4s', remaining[:8])
			if name != b'data':
				if name == b'name':
					remaining = remaining[size:]
					continue
				else:
					raise Exception  # TODO

			covers.append(MP4Cover.parse(remaining))
			remaining = remaining[size:]

		return cls(
			name='covr',
			value=covers,
		)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4FloatTag(MP4Tag):
	value = attrib(converter=float)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4FreeformTag(MP4Tag):
	@datareader
	@classmethod
	def _parse(cls, data, atom):
		atom_data = atom.read_data(data)

		size = struct.unpack('>I', atom_data[:4])[0]
		description = atom_data[12:size].decode('iso-8859-1')
		position = size
		size = struct.unpack('>I', atom_data[position : position + 4])[0]
		name = atom_data[position + 12 : position + size].decode('iso-8859-1')
		position += size
		value = []

		while position < atom._size - 8:
			size, atom_name = struct.unpack('>I4s', atom_data[position : position + 8])
			if atom_name != b'data':
				raise Exception  # TODO

			version = atom_data[position + 8]
			data_type = MP4AtomDataType(struct.unpack('>I', b'\x00' + atom_data[position + 9 : position + 12])[0])

			value.append(
				MP4Freeform(
					description=description,
					name=name,
					data_type=data_type,
					value=atom_data[position + 16 : position + size],
				)
			)
			position += size

		return cls(
			name=atom.type,
			value=value,
		)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4GenreTag(MP4Tag):
	@datareader
	@classmethod
	def _parse(cls, data, atom):
		values = []
		for _, _, atom_data in cls._parse_atom(data, atom):
			if len(atom_data) != 2:
				raise Exception  # TODO

			genre_index = struct.unpack('>H', atom_data)[0]
			try:
				genre = ID3v1Genres[genre_index]
			except IndexError:
				raise Exception  # TODO
			else:
				values.append(genre)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4IntegerTag(MP4Tag):
	@datareader
	@classmethod
	def _parse(cls, data, atom):
		values = []
		for _, _, atom_data in cls._parse_atom(data, atom):
			if len(atom_data) == 1:
				value = struct.unpack('>b', atom_data)[0]
			elif len(atom_data) == 2:
				value = struct.unpack('>h', atom_data)[0]
			elif len(atom_data) == 3:
				value = struct.unpack('>i', atom_data + b'\x00')[0]
			elif len(atom_data) == 4:
				value = struct.unpack('>i', atom_data)[0]
			elif len(atom_data) == 8:
				value = struct.unpack('>q', atom_data)[0]
			else:
				raise Exception  # TODO

			values.append(value)

		return cls(
			name=atom.type,
			value=values,
		)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4NumberTag(MP4Tag):
	@datareader
	@classmethod
	def _parse(cls, data, atom):
		atom_data = atom.read_data(data)

		number, total = struct.unpack('>HH', atom_data[18:22])

		return cls(
			name=atom.type,
			value=f"{number}/{total}"
		)

	@property
	def number(self):
		return self.value.split('/')[0]

	@property
	def total(self):
		try:
			tot = self.value.split('/')[1]
		except IndexError:
			tot = None

		return tot


@attrs(
	repr=False,
	kw_only=True,
)
class MP4TextTag(MP4Tag):
	@datareader
	@classmethod
	def _parse(cls, data, atom):
		values = []
		for _, _, atom_data in cls._parse_atom(data, atom):
			try:
				values.append(atom_data.decode('utf-8'))
			except UnicodeDecodeError:
				raise  # TODO

		return cls(
			name=atom.type,
			value=values,
		)


MP4TagTypes = {
	'----': MP4FreeformTag,
	'©ART': MP4TextTag,
	'©alb': MP4TextTag,
	'©cmt': MP4TextTag,
	'©day': MP4TextTag,
	'©gen': MP4TextTag,
	'©grp': MP4TextTag,
	'©lyr': MP4TextTag,
	'©mvc': MP4IntegerTag,
	'©mvi': MP4IntegerTag,
	'©nam': MP4TextTag,
	'©too': MP4TextTag,
	'©wrt': MP4TextTag,
	'aART': MP4TextTag,
	'akID': MP4IntegerTag,
	'atID': MP4IntegerTag,
	'catg': MP4TextTag,
	'cmID': MP4IntegerTag,
	'cnID': MP4IntegerTag,
	'covr': MP4CoverTag,
	'cpil': MP4BooleanTag,
	'cprt': MP4TextTag,
	'desc': MP4TextTag,
	'disk': MP4NumberTag,
	'egid': MP4TextTag,
	'geID': MP4IntegerTag,
	'gnre': MP4GenreTag,
	'hdvd': MP4IntegerTag,
	'keyw': MP4TextTag,
	'pcst': MP4BooleanTag,
	'pgap': MP4BooleanTag,
	'plID': MP4IntegerTag,
	'purd': MP4TextTag,
	'purl': MP4TextTag,
	'rtng': MP4IntegerTag,
	'sfID': MP4IntegerTag,
	'shwm': MP4IntegerTag,
	'soaa': MP4TextTag,
	'soal': MP4TextTag,
	'soar': MP4TextTag,
	'soco': MP4TextTag,
	'sonm': MP4TextTag,
	'sosn': MP4TextTag,
	'stik': MP4IntegerTag,
	'tmpo': MP4IntegerTag,
	'trkn': MP4NumberTag,
	'tves': MP4IntegerTag,
	'tvsh': MP4TextTag,
	'tvsn': MP4IntegerTag,
}
