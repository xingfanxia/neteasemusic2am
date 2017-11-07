#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import os
import sys
import struct
import time
import json
import csv
import urllib2
import traceback


def save_songs(songs, playlist_path):
    with open(playlist_path, 'w') as playlist_file:
        fieldnames = ['URI', 'Track Name', 'Artist Name',
                      'Album Name', 'Disc Number', 'Track Number',
                      'Track Duration (ms)', 'Added By', 'Added At',
                      'iTunes Identifier', 'Imported']
        writer = csv.DictWriter(playlist_file, fieldnames=fieldnames)
        writer.writeheader()
        for song in songs:
            for k, v in song.items():
                if isinstance(v, unicode):
                    song[k] = v.encode('utf-8')
            writer.writerow(song)

def load_songs(playlist_path):
    with open(playlist_path) as playlist_file:
        reader = csv.DictReader(playlist_file)
        songs = []
        for song in reader:
            for k, v in song.items():
                if not isinstance(v, unicode):
                    song[k] = v.decode('utf-8')
            songs.append(song)
        return songs


def download_playlist(playlist_id):
    cookie_opener = urllib2.build_opener()
    cookie_opener.addheaders.append(('Cookie', 'appver=2.0.2'))
    cookie_opener.addheaders.append(('Referer', 'http://music.163.com'))
    urllib2.install_opener(cookie_opener)
    url = 'http://music.163.com/api/playlist/detail?id=' + playlist_id
    resp = urllib2.urlopen(url)
    response = json.loads(resp.read().decode('utf-8'))
    return response['result']['tracks']


def track_to_songs(tracks):
    songs = []
    for track in tracks:
        row = {}
        row['URI'] = track['mp3Url']
        row['Track Name'] = re.sub(r'[\(|\[].+[\)|\]]', '',
                                   track['name']).strip()
        artists = track['artists']
        row['Artist Name'] = ', '.join([artist['name'] for artist in
                                        artists])
        if track.get('album', None):
            row['Album Name'] = track['album']['name']
        songs.append(row)
    return songs


def retrieve_itunes_identifier(title, artist):
    headers = {
        'X-Apple-Store-Front': '143446-10,32 ab:rSwnYxS0 t:music2',
        'X-Apple-Tz': '7200'
    }
    url = 'https://itunes.apple.com/WebObjects/MZStore.woa/wa/search' +\
          '?clientApplication=MusicPlayer&term=' +\
          urllib2.quote(title.encode('utf-8') if
                        isinstance(title, unicode) else title)
    request = urllib2.Request(url, None, headers)
    try:
        response = urllib2.urlopen(request)
        json_response = json.loads(response.read().decode('utf-8'))
        results = json_response.get('storePlatformData', {}).\
            get('lockup', {}).get('results', {}).values()
        songs = [result for result in results if result['kind'] == 'song']

        # Attempt to match by title & artist
        for song in songs:
            if song['name'].lower() == title.lower() and\
               (song['artistName'].lower() in artist.lower() or
                    artist.lower() in song['artistName'].lower()):
                return song['id']

        # Attempt to match by title if we didn't get a title & artist match
        for song in songs:
            if song['name'].lower() == title.lower():
                return song['id']
    except Exception as e:
        return e


def match_itunes_identifier(songs):
    for song in songs:
        if len(song.get('iTunes Identifier', '')) > 0:
            continue
        title, artist = song['Track Name'], song['Artist Name']
        while True:
            result = retrieve_itunes_identifier(title, artist)
            if isinstance(result, urllib2.HTTPError) and\
               (result.code == 503 or result.code == 504):
                time.sleep(5)
                continue
            if isinstance(result, Exception):
                traceback.print_exc()
                print(u'[Match Fail]{} - {}: {}'.format(title, artist,
                                                        result))
            elif result:
                print(u'[Matched]{} - {} => {}'.format(title, artist,
                                                       result))
                song['iTunes Identifier'] = result
            break


def construct_request_body(timestamp, itunes_identifier):
    hex = '61 6a 43 41 00 00 00 45 6d 73 74 63 00 00 00 04 55 94 17 a3 6d ' +\
          '6c 69 64 00 00 00 04 00 00 00 00 6d 75 73 72 00 00 00 04 00 00 ' +\
          '00 81 6d 69 6b 64 00 00 00 01 02 6d 69 64 61 00 00 00 10 61 65 ' +\
          '41 69 00 00 00 08 00 00 00 00 11 8c d9 2c 00'
    body = bytearray.fromhex(hex)
    body[16:20] = struct.pack('>I', timestamp)
    body[-5:] = struct.pack('>I', itunes_identifier)
    return body


def add_song(itunes_identifier, headers):
    data = construct_request_body(int(time.time()), itunes_identifier)
    request = urllib2.Request('https://ld-5.itunes.apple.com/WebObjects/' +
                              'MZDaap.woa/daap/databases/1/cloud-add', data,
                              headers)
    urllib2.urlopen(request)


def add_songs(songs):
    headers = {
        'X-Apple-Store-Front': '143465-19,32',
        'Client-iTunes-Sharing-Version': '3.12',
        'Accept-Language': 'zh-cn, zh;q=0.75, en-us;q=0.50, en;q=0.25',
        'Client-Cloud-DAAP-Version': '1.0/iTunes-12.3.0.44',
        'Accept-Encoding': 'gzip',
        'X-Apple-itre': '0',
        'Client-DAAP-Version': '3.13',
        'User-Agent': sys.argv[1],
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-dmap-tagged',
        'X-Dsid': sys.argv[2],
        'Cookie': sys.argv[3],
        'X-Guid': sys.argv[4],
        'Content-Length': '77'
    }
    for song in songs:
        if song.get('Imported', None) in ['true', 'not found']:
            continue
        title, artist = song['Track Name'], song['Artist Name']
        itunes_identifier = song.get('iTunes Identifier', None)
        if not itunes_identifier or not itunes_identifier.isdigit():
            continue
        while True:
            try:
                add_song(int(itunes_identifier), headers)
                song['Imported'] = 'true'
                print(u'[Imported]{} - {}'.format(title, artist))
                time.sleep(5)
            except Exception as e:
                if isinstance(e, urllib2.HTTPError):
                    if e.code == 503 or e.code == 504:
                        time.sleep(30)
                        continue
                    if e.code == 404:
                        song['Imported'] = 'not found'
                else:
                    traceback.print_exc()
                print(u'[Import Failed]{} - {}: {}'.
                      format(title, artist, str(e)))
            break


def main():
    songs = []
    try:
        playlist_id = sys.argv[5]
        playlist_path = './{0}.csv'.format(playlist_id)
        if not os.path.exists(playlist_path):
            tracks = download_playlist(playlist_id)
            songs = track_to_songs(tracks)
        else:
            songs = load_songs(playlist_path)

        print('Matching........................')
        match_itunes_identifier(songs)

        print('Importing........................')
        add_songs(songs)
    finally:
        if len(songs) > 0:
            save_songs(songs, playlist_path)

if __name__ == '__main__':
    main()
