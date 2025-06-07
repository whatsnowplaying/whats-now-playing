#!/usr/bin/env python3
"""
Streamlined MusicBrainz XML parser for nowplaying usage.
Based on musicbrainzngs library mbxml.py.
Original work:
Copyright 2011-2023 Alastair Porter, Adrian Sampson, and others.
Licensed under BSD-2-Clause license.
This derivative work contains only the parsing functions needed by nowplaying
and is optimized for async usage.
"""
import xml.etree.ElementTree as ET
from typing import Any


def parse_message(message: str | bytes) -> dict[str, Any]:
    """Parse a MusicBrainz XML response message"""
    if isinstance(message, str):
        message = message.encode('utf-8')
    try:
        root = ET.fromstring(message)
    except ET.ParseError as parse_error:
        raise ValueError(f"Invalid XML response: {parse_error}") from parse_error
    result = {}
    # Main element parsers we need
    parsers = {
        "artist": parse_artist,
        "artist-list": parse_artist_list,
        "recording": parse_recording,
        "recording-list": parse_recording_list,
        "release": parse_release,
        "release-list": parse_release_list,
        "release-group": parse_release_group,
        "release-group-list": parse_release_group_list,
        "isrc": parse_isrc,
        "message": parse_response_message
    }
    # Parse root element and its children
    for child in root:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag in parsers:
            result[tag] = parsers[tag](child)
            # Check for count and offset attributes on list elements
            if tag.endswith('-list'):
                if child.get('count'):
                    result[f"{tag.replace('-list', '')}-count"] = int(child.get('count'))
                if child.get('offset'):
                    result[f"{tag.replace('-list', '')}-offset"] = int(child.get('offset'))
        elif tag == "count":
            result[f"{root.tag.split('}')[-1]}-count"] = int(child.text or 0)
        elif tag == "offset":
            result[f"{root.tag.split('}')[-1]}-offset"] = int(child.text or 0)
    return result


def parse_response_message(element: ET.Element) -> dict[str, Any]:
    """Parse error/response messages"""
    texts = []
    for child in element:
        if child.tag.endswith('text') and child.text:
            texts.append(child.text)
    return {"text": texts}


def parse_artist_list(element: ET.Element) -> list[dict[str, Any]]:
    """Parse artist-list element"""
    return [parse_artist(artist) for artist in element if artist.tag.endswith('artist')]


def parse_artist(element: ET.Element) -> dict[str, Any]:
    """Parse artist element"""
    artist = {}
    # Parse attributes (id, type, ext:score)
    if element.get("id"):
        artist["id"] = element.get("id")
    if element.get("type"):
        artist["type"] = element.get("type")
    # Parse child elements
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == "name" and child.text:
            artist["name"] = child.text
        elif tag == "sort-name" and child.text:
            artist["sort-name"] = child.text
        elif tag == "disambiguation" and child.text:
            artist["disambiguation"] = child.text
        elif tag == "type" and child.text:
            artist["type"] = child.text
        elif tag == "life-span":
            artist["life-span"] = parse_lifespan(child)
        elif tag == "url-relation-list":
            artist["url-relation-list"] = parse_url_relation_list(child)
    return artist


def parse_recording_list(element: ET.Element) -> list[dict[str, Any]]:
    """Parse recording-list element"""
    return [
        parse_recording(recording) for recording in element if recording.tag.endswith('recording')
    ]


def parse_recording(element: ET.Element) -> dict[str, Any]:
    """Parse recording element"""
    recording = {}
    # Parse attributes (id, ext:score)
    if element.get("id"):
        recording["id"] = element.get("id")
    # Parse child elements
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == "title" and child.text:
            recording["title"] = child.text
        elif tag == "disambiguation" and child.text:
            recording["disambiguation"] = child.text
        elif tag == "length" and child.text:
            recording["length"] = int(child.text)
        elif tag == "artist-credit":
            artist_credit = parse_artist_credit(child)
            recording["artist-credit"] = artist_credit
            recording["artist-credit-phrase"] = get_artist_credit_phrase(artist_credit)
        elif tag == "release-list":
            release_list = parse_release_list(child)
            recording["release-list"] = release_list
            recording["release-count"] = len(release_list)
        elif tag == "first-release-date" and child.text:
            recording["first-release-date"] = child.text
        elif tag == "genre-list":
            recording["genre-list"] = parse_genre_list(child)
    return recording


def parse_release_list(element: ET.Element) -> list[dict[str, Any]]:
    """Parse release-list element"""
    return [parse_release(release) for release in element if release.tag.endswith('release')]


def parse_release(element: ET.Element) -> dict[str, Any]:
    """Parse release element"""
    release = {}
    # Parse attributes (id, ext:score)
    if element.get("id"):
        release["id"] = element.get("id")
    # Parse child elements
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == "title" and child.text:
            release["title"] = child.text
        elif tag == "disambiguation" and child.text:
            release["disambiguation"] = child.text
        elif tag == "date" and child.text:
            release["date"] = child.text
        elif tag == "country" and child.text:
            release["country"] = child.text
        elif tag == "status" and child.text:
            release["status"] = child.text
        elif tag == "artist-credit":
            artist_credit = parse_artist_credit(child)
            release["artist-credit"] = artist_credit
            release["artist-credit-phrase"] = get_artist_credit_phrase(artist_credit)
        elif tag == "release-group":
            release["release-group"] = parse_release_group(child)
        elif tag == "label-info-list":
            release["label-info-list"] = parse_label_info_list(child)
        elif tag == "cover-art-archive":
            release["cover-art-archive"] = parse_cover_art_archive(child)
    return release


def parse_release_group_list(element: ET.Element) -> list[dict[str, Any]]:
    """Parse release-group-list element"""
    return [parse_release_group(rg) for rg in element if rg.tag.endswith('release-group')]


def parse_release_group(element: ET.Element) -> dict[str, Any]:
    """Parse release-group element"""
    release_group = {}
    # Parse attributes (id, type, ext:score)
    if element.get("id"):
        release_group["id"] = element.get("id")
    if element.get("type"):
        release_group["type"] = element.get("type")
    # Parse child elements
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == "title" and child.text:
            release_group["title"] = child.text
        elif tag == "disambiguation" and child.text:
            release_group["disambiguation"] = child.text
        elif tag == "primary-type" and child.text:
            release_group["primary-type"] = child.text
        elif tag == "secondary-type-list":
            release_group["secondary-type-list"] = [st.text for st in child if st.text]
        elif tag == "first-release-date" and child.text:
            release_group["first-release-date"] = child.text
        elif tag == "artist-credit":
            artist_credit = parse_artist_credit(child)
            release_group["artist-credit"] = artist_credit
            release_group["artist-credit-phrase"] = get_artist_credit_phrase(artist_credit)
    return release_group


def parse_isrc(element: ET.Element) -> dict[str, Any]:
    """Parse isrc element"""
    isrc = {}
    # Parse attributes (id)
    if element_id := element.get("id"):
        isrc["id"] = element_id
    # Parse child elements
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == "recording-list":
            isrc["recording-list"] = parse_recording_list(child)
    return isrc


def parse_artist_credit(element: ET.Element) -> list[dict[str, Any] | str]:
    """Parse artist-credit element"""
    credit = []
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == "name-credit":
            name_credit = {}
            for nc_child in child:
                nc_tag = nc_child.tag.split('}')[-1] if '}' in nc_child.tag else nc_child.tag
                if nc_tag == "name" and nc_child.text:
                    name_credit["name"] = nc_child.text
                elif nc_tag == "artist":
                    name_credit["artist"] = parse_artist(nc_child)
            credit.append(name_credit)
            # Check for joinphrase attribute on the name-credit element
            if joinphrase := child.get("joinphrase"):
                credit.append(joinphrase)
        elif child.text:
            # Join phrase as text element (fallback)
            credit.append(child.text)
    return credit


def get_artist_credit_phrase(artist_credit: list[dict[str, Any] | str]) -> str:
    """Convert artist credit to display phrase"""
    phrase = ""
    for item in artist_credit:
        if isinstance(item, dict):
            # Check if this is a name-credit with nested artist
            if "artist" in item and "name" in item["artist"]:
                phrase += item["artist"]["name"]
            elif "name" in item:
                phrase += item["name"]
        else:
            phrase += item
    return phrase


def parse_lifespan(element: ET.Element) -> dict[str, Any]:
    """Parse life-span element"""
    lifespan = {}
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if text := child.text:
            lifespan[tag] = text
    return lifespan


def parse_url_relation_list(element: ET.Element) -> list[dict[str, Any]]:
    """Parse url-relation-list element"""
    relations = []
    for child in element:
        if child.tag.endswith('relation'):
            relation = {}
            # Parse attributes (type, type-id)
            if child.get("type"):
                relation["type"] = child.get("type")
            if child.get("type-id"):
                relation["type-id"] = child.get("type-id")
            for rel_child in child:
                rel_tag = rel_child.tag.split('}')[-1] if '}' in rel_child.tag else rel_child.tag
                if rel_tag == "target" and rel_child.text:
                    relation["target"] = rel_child.text
            relations.append(relation)
    return relations


def parse_label_info_list(element: ET.Element) -> list[dict[str, Any]]:  # pylint: disable=too-many-nested-blocks
    """Parse label-info-list element"""
    labels = []
    for child in element:  # pylint: disable=too-many-nested-blocks
        if child.tag.endswith('label-info'):
            label_info = {}
            for li_child in child:
                li_tag = li_child.tag.split('}')[-1] if '}' in li_child.tag else li_child.tag
                if li_tag == "label":
                    label = {}
                    # Parse attributes (like type)
                    if li_child.get("id"):
                        label["id"] = li_child.get("id")
                    if li_child.get("type"):
                        label["type"] = li_child.get("type")
                    # Parse child elements (like name)
                    for label_child in li_child:
                        label_tag = (label_child.tag.split('}')[-1]
                                     if '}' in label_child.tag else label_child.tag)
                        if (label_tag in ["name", "sort-name", "disambiguation"]
                                and label_child.text):
                            label[label_tag] = label_child.text
                    label_info["label"] = label
            labels.append(label_info)
    return labels


def parse_cover_art_archive(element: ET.Element) -> dict[str, Any]:
    """Parse cover-art-archive element"""
    caa = {}
    for child in element:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if text := child.text:
            caa[tag] = text
    return caa


def parse_genre_list(element: ET.Element) -> list[dict[str, Any]]:  # pylint: disable=too-many-nested-blocks
    """Parse genre-list element"""
    genres = []
    for child in element:
        if child.tag.endswith('genre'):
            genre = {}
            # Parse attributes (count, id)
            if child.get("count"):
                genre["count"] = int(child.get("count"))
            if child.get("id"):
                genre["id"] = child.get("id")
            for genre_child in child:
                genre_tag = (genre_child.tag.split('}')[-1]
                             if '}' in genre_child.tag else genre_child.tag)
                if genre_tag == "name" and genre_child.text:
                    genre["name"] = genre_child.text
            genres.append(genre)
    return genres
