__all__ = [
	'MP4',
	'MP4Atom',
	'MP4Atoms',
	'MP4StreamInfo',
	'MP4Tags',
]

import os
import struct
from collections import defaultdict

from attr import attrib, attrs
from bidict import frozenbidict
from tbm_utils import (
	AttrMapping,
	LabelList,
	datareader,
)

from .mp4_tags import MP4Tag
from .tables import (
	MP4AudioObjectTypes,
	MP4SamplingFrequencies,
)
from ..exceptions import (
	FormatError,
	UnsupportedFormat,
)
from ..models import (
	Format,
	StreamInfo,
	Tags,
)

try:  # pragma: nocover
	import bitstruct.c as bitstruct
except ImportError:  # pragma: nocover
	import bitstruct

PARENT_ATOMS = {
	'ilst',
	'mdia',
	'meta',
	'minf',
	'moof',
	'moov',
	'stbl',
	'traf',
	'trak',
	'udta'
}
EXT_DESCRIPTOR_TYPES = {b'\x80', b'\x81', b'\xFE'}


# TODO: Custom type?
@attrs(
	repr=False,
	kw_only=True,
)
class MP4Atom(AttrMapping):
	_start = attrib()
	_size = attrib()
	_data_start = attrib()
	type = attrib()  # noqa
	_children = attrib(default=[])

	def __repr__(self):
		repr_dict = {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

		return super().__repr__(repr_dict=repr_dict)

	@datareader
	@classmethod
	def parse(cls, data, level=0):
		children = []

		atom_start = data_start = data.tell()
		atom_header = data.read(8)

		try:
			atom_size, atom_type = struct.unpack('>I4s', atom_header[0:8])
			data_start += 8
		except struct.error:
			raise FormatError("Invalid MP4 atom.")

		atom_type = atom_type.decode('iso-8859-1')

		if atom_size == 1:
			try:
				atom_size = struct.unpack('>Q', data.read(8))[0]
				data_start += 8
			except struct.error:
				raise FormatError("Invalid MP4 atom.")

			if atom_size < 16:
				raise FormatError("Invalid MP4 atom.")
		elif atom_size == 0:
			if level != 0:
				raise FormatError("Invalid MP4 atom.")

			data.seek(0, os.SEEK_END)
			atom_size = data.tell() - atom_start
			data.seek(atom_start + 8, os.SEEK_SET)
		elif atom_size < 8:
			raise FormatError("Invalid MP4 atom.")

		if atom_type in PARENT_ATOMS:
			if atom_type == 'meta':
				data.seek(4, os.SEEK_CUR)

			while data.tell() < atom_start + atom_size:
				children.append(MP4Atom.parse(data, level + 1))
		else:
			data.seek(atom_start + atom_size, os.SEEK_SET)

		return cls(
			start=atom_start,
			size=atom_size,
			data_start=data_start,
			type=atom_type,
			children=children,
		)

	def get_child(self, path):
		if not path:
			return self

		if not self._children:
			raise KeyError("No children found.")

		if isinstance(path, str):
			path = path.split('.')

		for child in self._children:
			if child.type == path[0]:
				return child.get_child(path[1:])
		else:
			raise KeyError('Path not found.')

	@datareader
	def read_data(self, data):
		data.seek(self._data_start, os.SEEK_SET)
		atom_data = data.read(self._size - (self._data_start - self._start))

		return atom_data


# TODO: Custom type?
class MP4Atoms(LabelList):
	item_label = ('atom', 'atoms')

	def __init__(self, items):
		super().__init__(items)

	def __getitem__(self, path):
		if isinstance(path, str):
			path = path.split('.')

			for atom in self.data:
				if atom.type == path[0]:
					return atom.get_child(path[1:])
			else:
				raise KeyError(f'No atom of type {path[0]} found.')

		return list.__getitem__(self.data, path)

	@datareader
	@classmethod
	def parse(cls, data):
		atoms = []
		while True:
			try:
				atoms.append(MP4Atom.parse(data, level=0))
			except (FormatError, struct.error):
				break

		return cls(atoms)


class MP4Tags(Tags):
	FIELD_MAP = frozenbidict({
		'album': '©alb',
		'albumsort': 'soal',
		'albumartist': 'aART',
		'albumartistsort': 'soaa',
		'artist': '©ART',
		'artistsort': 'soar',
		'bpm': 'tmpo',
		'category': 'catg',
		'comment': '©cmt',
		'compilation': 'cpil',
		'composer': '©wrt',
		'composersort': 'soco',
		'copyright': 'cprt',
		'date': '©day',
		'description': 'desc',
		'discnumber': 'disk',
		'encodedby': '©too',
		'freeform': '----',
		'gapless': 'pgap',
		'genre': '©gen',
		'genre_id3': 'gnre',
		'grouping': '©grp',
		'keyword': 'keyw',
		'lyrics': '©lyr',
		'pictures': 'covr',
		'podcast': 'pcst',
		'podcasturl': 'purl',
		'rating': 'rtng',
		'title': '©nam',
		'titlesort': 'sonm',
		'tracknumber': 'trkn'
	})

	@datareader
	@classmethod
	def parse(cls, data, ilst):
		fields = defaultdict(list)

		for child in ilst._children:
			tag = MP4Tag.parse(data, child)
			if tag is None:  # TODO
				continue

			fields[tag.name] = tag.value

		return cls(**fields)


@attrs(
	repr=False,
	kw_only=True,
)
class MP4StreamInfo(StreamInfo):
	_start = attrib()
	_size = attrib()
	bit_depth = attrib()
	bitrate = attrib()
	channels = attrib()
	codec = attrib()
	codec_description = attrib()
	duration = attrib()
	sample_rate = attrib()

	@staticmethod
	def _parse_audio_sample_entry(ase_data):
		channels = struct.unpack(
			'>H',
			ase_data[16:18]
		)[0]

		bit_depth = struct.unpack(
			'>H',
			ase_data[18:20]
		)[0]

		sample_rate = struct.unpack(
			'>I',
			ase_data[22:26]
		)[0]

		return channels, bit_depth, sample_rate

	@datareader
	@staticmethod
	def _parse_esds(data):
		def _parse_audio_object_type(data):
			audio_object_type_index = data.readbits(5)
			audio_object_type_ext = None

			if audio_object_type_index == 31:
				data.readbits(5)

				audio_object_type_ext = data.readbits(6)
				audio_object_type_index = 32 + audio_object_type_ext

			return audio_object_type_index, audio_object_type_ext

		def _parse_sample_rate(data):
			sampling_frequency_index = data.readbits(4)
			if sampling_frequency_index == 15:
				sample_rate = data.readbits(24)
			else:
				try:
					sample_rate = MP4SamplingFrequencies[sampling_frequency_index]
				except IndexError:
					sample_rate = None

			return sample_rate
		version = data.readbits(8)
		if version != 0:
			raise Exception

		data.seek(3, os.SEEK_CUR)
		if data.readbits(8) == 3:
			while True:
				b = data.read(1)
				if b not in EXT_DESCRIPTOR_TYPES:
					break

			descriptor_type_length = b
			es_id = data.readbits(16)

			stream_dependence_flag, url_flag, ocr_stream_flag = bitstruct.unpack(
				'b1 b1 b1',
				data.read(1)
			)  # TODO: Stream priority

			if stream_dependence_flag:
				stream_dependence = data.readbits(16)
			if url_flag:
				url_length = data.readbits(8)
				url = data.read(url_length)
			if ocr_stream_flag:
				ocr = data.readbits(16)

			if data.readbits(8) == 4:
				while True:
					b = data.read(1)
					if b not in EXT_DESCRIPTOR_TYPES:
						break

				object_type_indication = data.readbits(8)
				stream_type, up_stream, reserved = bitstruct.unpack(
					'u6 b1 u1',
					data.read(1)
				)

				if (
					object_type_indication != 64
					or stream_type != 5
				):
					raise Exception

				buffer_size = data.readbits(24)
				max_bitrate = data.readbits(32)
				average_bitrate = data.readbits(32)

				if data.readbits(8) == 5:
					while True:
						b = data.read(1)
						if b not in EXT_DESCRIPTOR_TYPES:
							break

					audio_object_type_index, audio_object_type_ext = _parse_audio_object_type(data)

					try:
						codec_description = MP4AudioObjectTypes[audio_object_type_index]
					except IndexError:
						codec_description = None

					sample_rate = _parse_sample_rate(data)

					channel_config = data.readbits(4)  # TODO: Channels

					spectral_band_replication = False
					parametric_stereo = False
					ext_sample_rate = None

					if audio_object_type_index in [5, 29]:
						audio_object_type_ext = 5
						spectral_band_replication = True

						if audio_object_type_index == 29:
							parametric_stereo = True

						ext_sample_rate = _parse_sample_rate(data)
						audio_object_type_index, _ = _parse_audio_object_type(data)

						if audio_object_type_index == 22:
							ext_channel_config = data.readbits(4)
					else:
						audio_object_type_ext = None

					if audio_object_type_index in [1, 2, 3, 4, 6, 7, 17, 19, 20, 21, 22, 23]:
						try:
							data.readbits(1)

							core_coder_dependence = data.readbits(1)
							if core_coder_dependence:
								data.readbits(14)

							extension_flag = data.readbits(1)

							if not channel_config:  # TODO
								element_instance_tag = data.readbits(4)
								object_type = data.readbits(2)
								sample_rate_index = data.readbits(4)
								num_front_channel_elements = data.readbits(4)
								num_side_channel_elements = data.readbits(4)
								num_back_channel_elements = data.readbits(4)
								num_lfe_channel_elements = data.readbits(2)
								num_associated_data_elements = data.readbits(3)
								num_valid_cc_elements = data.readbits(4)

								mono_mixdown_present = data.readbits(1)
								mono_mixdown = data.readbits(4)

								stereo_mixdown_present = data.readbits(1)
								stereo_mixdown = data.readbits(4)

								matrix_mixdown_present = data.readbits(1)
								matrix_mixdown = data.readbits(3)

								elements = (
									num_front_channel_elements + num_side_channel_elements + num_back_channel_elements
								)
								channels = 0
								for i in range(elements):
									channels += 1
									element_is_cpe = data.readbits(1)
									if element_is_cpe:
										channels += 1

									data.readbits(4)

								channels += num_lfe_channel_elements
								data.readbits(4 * num_lfe_channel_elements)
								data.readbits(4 * num_associated_data_elements)
								data.readbits(5 * num_valid_cc_elements)
								data.readbits(data.bit_count)
								comment_field_bytes = data.readbits(8)
								data.read(comment_field_bytes)

							if audio_object_type_index in [6, 20]:
								data.readbits(3)

							if extension_flag:
								if audio_object_type_index == 22:
									data.readbits(16)

								if audio_object_type_index in [17, 19, 20, 23]:
									data.readbits(3)

								extension_flag_3 = data.readbits(1)
								if extension_flag_3 != 0:
									raise Exception  # TODO
						except Exception:
							raise
					else:
						raise UnsupportedFormat("Not a supported MP4 audio object type.")

					if audio_object_type_index in [17, 19, 20, 21, 22, 23, 24, 25, 26, 27, 39]:
						ep_config = data.readbits(2)
						if ep_config in [2, 3]:
							raise UnsupportedFormat

					# TODO: Finish/check.
					if (
						audio_object_type_ext != 5
						and (len(data.peek()) * 8) - data.bit_count >= 16
					):
						sync_extension_type = data.readbits(11)
						if sync_extension_type == 695:
							audio_object_type_ext, _ = _parse_audio_object_type(data)

						if audio_object_type_ext == 5:
							spectral_band_replication = bool(data.readbits(1))
							if spectral_band_replication:
								ext_sample_rate = _parse_sample_rate(data)

								if (len(data.peek()) * 8) - data.bit_count >= 12:
									sync_extension_type = data.readbits(11)
									if sync_extension_type == 1352:
										parametric_stereo = bool(data.readbits(1))

						if audio_object_type_ext == 22:
							spectral_band_replication = bool(data.readbits(1))
							if spectral_band_replication:
								ext_sample_rate = _parse_sample_rate(data)
								ext_channel_config = data.readbits(4)

					if spectral_band_replication and parametric_stereo:
						codec_description = "AAC HE (v2)"
					elif spectral_band_replication:
						codec_description = "AAC HE (v1)"

		return (
			average_bitrate,
			sample_rate,
			codec_description,
		)

	@staticmethod
	def _parse_alac(alac_data):
		version = alac_data[0]
		if version != 0:
			raise Exception

		compatible_version = alac_data[8]
		if compatible_version != 0:
			raise UnsupportedFormat

		bit_depth = alac_data[9]
		channels = alac_data[13]
		bitrate = bitstruct.unpack('u32', alac_data[20:24])[0]
		sample_rate = bitstruct.unpack('u32', alac_data[24:28])[0]

		return bit_depth, channels, bitrate, sample_rate

	@staticmethod
	def _parse_ac3(ac3_data):
		_, _, _, acmod, lfeon, bitrate_index = bitstruct.unpack(
			'u2 u5 u3 u3 u1 u5',
			ac3_data[0:3]
		)

		channels = [2, 1, 2, 3, 3, 4, 4, 5][acmod] + lfeon

		try:
			bitrate = [
				32,
				40,
				48,
				56,
				64,
				80,
				96,
				112,
				128,
				160,
				192,
				224,
				256,
				320,
				384,
				448,
				512,
				576,
				640
			][bitrate_index] * 1000
		except IndexError:
			bitrate = None

		return channels, bitrate

	@staticmethod
	def _parse_mdhd(mdhd_data):
		if len(mdhd_data) < 4:
			raise Exception

		version = mdhd_data[0]
		flags = int.from_bytes(mdhd_data[1:4], 'big')

		if version == 0:
			offset = 8
			struct_pattern = '>2I'
		elif version == 1:
			offset = 16
			struct_pattern = '>IQ'
		else:
			raise Exception

		end = offset + struct.calcsize(struct_pattern)
		unit, size = struct.unpack(struct_pattern, mdhd_data[4:][offset:end])

		try:
			duration = size / unit
		except ZeroDivisionError:
			duration = 0

		return version, flags, size, duration

	@datareader
	@classmethod
	def parse(cls, data, atoms):
		try:
			moov = atoms['moov']
		except KeyError:
			raise

		for child in moov._children:
			if child.type == 'trak':
				trak = child

				hdlr = trak.get_child('mdia.hdlr')
				hdlr_data = hdlr.read_data(data)

				if hdlr_data[8:12] == b'soun':
					break
		else:
			raise Exception

		mdhd = trak.get_child('mdia.mdhd')
		version, flags, size, duration = cls._parse_mdhd(mdhd.read_data(data))

		if version != 0:
			raise Exception

		try:
			stsd = trak.get_child('mdia.minf.stbl.stsd')
		except KeyError:
			raise
		else:
			stsd_data = stsd.read_data(data)

			num_entries = struct.unpack(
				'>I',
				stsd_data[4:8]
			)[0]

			if num_entries == 0:
				raise Exception

			audio_sample_entry = MP4Atom.parse(stsd_data[8:])
			ase_data = audio_sample_entry.read_data(stsd_data[8:])
			codec = audio_sample_entry.type

			channels, bit_depth, sample_rate = (
				cls._parse_audio_sample_entry(ase_data)
			)

			extra = MP4Atom.parse(ase_data[28:])

			bitrate = None
			# TODO: Other formats.
			if codec == 'mp4a' and extra.type == 'esds':
				esds_data = extra.read_data(ase_data[28:])
				average_bitrate, sample_rate, codec_description = cls._parse_esds(esds_data)
			elif codec == 'alac' and extra.type == 'alac':
				alac_data = extra.read_data(ase_data[28:])
				bit_depth, channels, bitrate, sample_rate = cls._parse_alac(alac_data)
				codec_description = 'ALAC'
			elif codec == 'ac-3' and extra.type == 'dac3':
				ac3_data = extra.read_data(ase_data[28:])
				channels, bitrate_ = cls._parse_ac3(ac3_data)

				if bitrate_:
					bitrate = bitrate_

				codec_description = 'AC-3'
			else:
				raise UnsupportedFormat("Not a supported MP4 audio codec.")

		audio_start = atoms['mdat']._start
		audio_size = atoms['mdat']._size

		if not bitrate:
			bitrate = audio_size * 8 / duration

		return cls(
			start=audio_start,
			size=audio_size,
			bit_depth=bit_depth,
			bitrate=bitrate,
			channels=channels,
			codec=codec,
			codec_description=codec_description,
			duration=duration,
			sample_rate=sample_rate,
		)


class MP4(Format):
	@classmethod
	def parse(cls, data):
		self = super()._load(data)

		atoms = MP4Atoms.parse(self._obj)

		self.streaminfo = MP4StreamInfo.parse(data, atoms)

		try:
			ilst = atoms['moov.udta.meta.ilst']
		except KeyError:
			self.tags = MP4Tags()
		else:
			self.tags = MP4Tags.parse(data, ilst)

		self.pictures = self.tags.pop('pictures', [])

		self._obj.close()

		return self
