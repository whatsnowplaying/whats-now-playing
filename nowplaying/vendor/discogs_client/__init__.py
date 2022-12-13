__version__ = '2.6'
__version_info__ = tuple(int(i) for i in __version__.split('.') if i.isdigit())

from nowplaying.vendor.discogs_client.client import Client
from nowplaying.vendor.discogs_client.models import Artist, Release, Master, Label, User, \
    Listing, Track, Price, Video, List, ListItem, Inventory, Wantlist, \
    WantlistItem, CollectionItemInstance, CollectionFolder, Order, OrderMessage, OrderMessagesList
from nowplaying.vendor.discogs_client.utils import Condition, Sort, Status
