"""
StagelinQ Value Names

This module provides constants for known StagelinQ state value names.
"""

# Global constants
CLIENT_LIBRARIAN_DEVICES_CONTROLLER_CURRENT_DEVICE = (
    "/Client/Librarian/DevicesController/CurrentDevice"
)
CLIENT_LIBRARIAN_DEVICES_CONTROLLER_HAS_SD_CARD_CONNECTED = (
    "/Client/Librarian/DevicesController/HasSDCardConnected"
)
CLIENT_LIBRARIAN_DEVICES_CONTROLLER_HAS_USB_DEVICE_CONNECTED = (
    "/Client/Librarian/DevicesController/HasUsbDeviceConnected"
)
CLIENT_PREFERENCES_LAYER_A = "/Client/Preferences/LayerA"
CLIENT_PREFERENCES_LAYER_B = "/Client/Preferences/LayerB"
CLIENT_PREFERENCES_PLAYER = "/Client/Preferences/Player"
CLIENT_PREFERENCES_PLAYER_JOG_COLOR_A = "/Client/Preferences/PlayerJogColorA"
CLIENT_PREFERENCES_PLAYER_JOG_COLOR_B = "/Client/Preferences/PlayerJogColorB"
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_1 = (
    "/Client/Preferences/Profile/Application/PlayerColor1"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_1A = (
    "/Client/Preferences/Profile/Application/PlayerColor1A"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_1B = (
    "/Client/Preferences/Profile/Application/PlayerColor1B"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_2 = (
    "/Client/Preferences/Profile/Application/PlayerColor2"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_2A = (
    "/Client/Preferences/Profile/Application/PlayerColor2A"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_2B = (
    "/Client/Preferences/Profile/Application/PlayerColor2B"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_3 = (
    "/Client/Preferences/Profile/Application/PlayerColor3"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_3A = (
    "/Client/Preferences/Profile/Application/PlayerColor3A"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_3B = (
    "/Client/Preferences/Profile/Application/PlayerColor3B"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_4 = (
    "/Client/Preferences/Profile/Application/PlayerColor4"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_4A = (
    "/Client/Preferences/Profile/Application/PlayerColor4A"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_PLAYER_COLOR_4B = (
    "/Client/Preferences/Profile/Application/PlayerColor4B"
)
CLIENT_PREFERENCES_PROFILE_APPLICATION_SYNC_MODE = (
    "/Client/Preferences/Profile/Application/SyncMode"
)
ENGINE_DECK_COUNT = "/Engine/DeckCount"
ENGINE_MASTER_MASTER_TEMPO = "/Engine/Master/MasterTempo"
ENGINE_SYNC_NETWORK_MASTER_STATUS = "/Engine/Sync/Network/MasterStatus"
GUI_DECKS_DECK_ACTIVE_DECK = "/GUI/Decks/Deck/ActiveDeck"
GUI_VIEW_LAYER_LAYER_B = "/GUI/ViewLayer/LayerB"
MIXER_CH1_FADER_POSITION = "/Mixer/CH1faderPosition"
MIXER_CH2_FADER_POSITION = "/Mixer/CH2faderPosition"
MIXER_CH3_FADER_POSITION = "/Mixer/CH3faderPosition"
MIXER_CH4_FADER_POSITION = "/Mixer/CH4faderPosition"
MIXER_CHANNEL_ASSIGNMENT_1 = "/Mixer/ChannelAssignment1"
MIXER_CHANNEL_ASSIGNMENT_2 = "/Mixer/ChannelAssignment2"
MIXER_CHANNEL_ASSIGNMENT_3 = "/Mixer/ChannelAssignment3"
MIXER_CHANNEL_ASSIGNMENT_4 = "/Mixer/ChannelAssignment4"
MIXER_CROSSFADER_POSITION = "/Mixer/CrossfaderPosition"
MIXER_NUMBER_OF_CHANNELS = "/Mixer/NumberOfChannels"


class DeckValueNames:
    """Helper class for generating deck-specific value names."""

    def __init__(self, deck_index: int):
        self.deck_index = deck_index

    def pads_view(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Pads/View"

    def track_artist_name(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/ArtistName"

    def track_bleep(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Bleep"

    def track_cue_position(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/CuePosition"

    def track_current_bpm(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/CurrentBPM"

    def track_current_key_index(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/CurrentKeyIndex"

    def track_current_loop_in_position(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/CurrentLoopInPosition"

    def track_current_loop_out_position(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/CurrentLoopOutPosition"

    def track_current_loop_size_in_beats(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/CurrentLoopSizeInBeats"

    def track_key_lock(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/KeyLock"

    def track_loop_enable_state(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/LoopEnableState"

    def track_play_pause_led_state(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/PlayPauseLEDState"

    def track_sample_rate(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/SampleRate"

    def track_song_analyzed(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/SongAnalyzed"

    def track_song_loaded(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/SongLoaded"

    def track_song_name(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/SongName"

    def track_sound_switch_guid(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/SoundSwitchGuid"

    def track_track_bytes(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/TrackBytes"

    def track_track_data(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/TrackData"

    def track_track_length(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/TrackLength"

    def track_track_name(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/TrackName"

    def track_track_network_path(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/TrackNetworkPath"

    def track_track_uri(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/TrackUri"

    def track_track_was_played(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/TrackWasPlayed"

    def track_loop_quick_loop_1(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop1"

    def track_loop_quick_loop_2(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop2"

    def track_loop_quick_loop_3(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop3"

    def track_loop_quick_loop_4(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop4"

    def track_loop_quick_loop_5(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop5"

    def track_loop_quick_loop_6(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop6"

    def track_loop_quick_loop_7(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop7"

    def track_loop_quick_loop_8(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Track/Loop/QuickLoop8"

    def current_bpm(self) -> str:
        return f"/Engine/Deck{self.deck_index}/CurrentBPM"

    def deck_is_master(self) -> str:
        return f"/Engine/Deck{self.deck_index}/DeckIsMaster"

    def external_mixer_volume(self) -> str:
        return f"/Engine/Deck{self.deck_index}/ExternalMixerVolume"

    def external_scratch_wheel_touch(self) -> str:
        return f"/Engine/Deck{self.deck_index}/ExternalScratchWheelTouch"

    def play(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Play"

    def play_state(self) -> str:
        return f"/Engine/Deck{self.deck_index}/PlayState"

    def play_state_path(self) -> str:
        return f"/Engine/Deck{self.deck_index}/PlayStatePath"

    def speed(self) -> str:
        return f"/Engine/Deck{self.deck_index}/Speed"

    def speed_neutral(self) -> str:
        return f"/Engine/Deck{self.deck_index}/SpeedNeutral"

    def speed_offset_down(self) -> str:
        return f"/Engine/Deck{self.deck_index}/SpeedOffsetDown"

    def speed_offset_up(self) -> str:
        return f"/Engine/Deck{self.deck_index}/SpeedOffsetUp"

    def speed_range(self) -> str:
        return f"/Engine/Deck{self.deck_index}/SpeedRange"

    def speed_state(self) -> str:
        return f"/Engine/Deck{self.deck_index}/SpeedState"

    def sync_mode(self) -> str:
        return f"/Engine/Deck{self.deck_index}/SyncMode"


# Pre-defined deck instances
EngineDeck1 = DeckValueNames(1)
EngineDeck2 = DeckValueNames(2)
EngineDeck3 = DeckValueNames(3)
EngineDeck4 = DeckValueNames(4)
