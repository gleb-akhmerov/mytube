from datetime import datetime, timezone
from urllib import request
import re
import json
from time import sleep
import traceback

from bs4 import BeautifulSoup
from youtube_dl import YoutubeDL


def parse_date(s):
  found = re.match(r'(\d\d\d\d)-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)\+\d\d:\d\d', s)
  year, month, day, hour, minute, second = map(int, found.groups())
  return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def pickup(channels):
  videos = []
  for chan in channels:
    print(f'Updating {chan["name"]}')
    chan_url = 'https://www.youtube.com/feeds/videos.xml?channel_id=' + chan['id']
    with request.urlopen(chan_url, timeout=5) as rss:
      for entry in BeautifulSoup(rss, "xml").find_all("entry"):
        id = entry.find('yt:videoId').string
        item = {
          "title": entry.title.string,
          "id": entry.find('yt:videoId').string,
          "date-published": parse_date(entry.published.string).timestamp(),
          "channel-id": chan['id'],
          "description": entry.find('media:description').string,
        }
        videos.append(item)
    print(f'Done updating {chan["name"]}')
  return videos


def updater(conn):
  while True:
    try:
      channels = conn.execute('select * from Channel')
      videos = pickup(channels)
      with conn:
        for vid in videos:
          add_video(conn, vid)
    except Exception as e:
      traceback.print_exc()
    sleep(10 * 60)


def get_all_videos_from_channel(id):
  with YoutubeDL({'ignoreerrors': True}) as ydl:
    videos = ydl.extract_info('https://www.youtube.com/channel/' + id, download=False)['entries']
  return [{'id': v['id'],
           'title': v['title'],
           'date-published': datetime(*map(int, re.match(r'(\d\d\d\d)(\d\d)(\d\d)', v['upload_date']).groups()), tzinfo=timezone.utc).timestamp(),
           'description': v['description'],
           'channel-id': v['channel_id'],}
          for v in videos
          if v is not None]


def load_all_videos(conn):
  while True:
    for chan in conn.execute("""select Channel.* from ChannelNeedsVideoSync
                                join Channel on Channel.id = ChannelNeedsVideoSync.id"""):
      print("Loading all videos from " + chan['name'])

      videos = get_all_videos_from_channel(chan['id'])
      with conn:
        for vid in videos:
          add_video(conn, vid)
        conn.execute('delete from ChannelNeedsVideoSync where id = ?', (chan['id'],))

      print("Done loading all videos from " + chan['name'])
    sleep(10)


def get_playlists_from_channel(id):
  playlists = []
  with YoutubeDL({'quiet': False}) as ydl:
    for e in ydl.extract_info('https://www.youtube.com/channel/' + id + '/playlists?view=1', download=False, process=False)['entries']:
      playlist = ydl.extract_info(e['url'], download=False, process=False)
      playlists.append({
        'id': playlist['id'],
        'title': playlist['title'],
        'video-ids': [x['id'] for x in playlist['entries']],
      })
  return playlists


def load_playlists(conn):
  while True:
    for chan in conn.execute("""select Channel.* from ChannelNeedsPlaylistSync
                                join Channel on Channel.id = ChannelNeedsPlaylistSync.id"""):
      print("Loading playlists from " + chan['name'])

      playlists = get_playlists_from_channel(chan['id'])
      with conn:
        for playlist in playlists:
          conn.execute('insert into Playlist (id, channel_id, name) values (?, ?, ?)', (playlist['id'], chan['id'], playlist['title']))
          for n, video_id in enumerate(playlist['video-ids'], start=1):
            conn.execute('insert into PlaylistVideo (playlist_id, playlist_row, video_id) values (?, ?, ?)', (playlist['id'], n, video_id))
        conn.execute('delete from ChannelNeedsPlaylistSync where id = ?', (chan['id'],))

      print("Done loading playlists from " + chan['name'])
    sleep(10)


def add_video(conn, video):
  conn.execute("""
    insert into Video
      (id, channel_id, title, description, date)
    values
      (?, ?, ?, ?, ?)
    on conflict(id) do update set
      title       = excluded.title,
      description = excluded.description,
      date        = excluded.date
  """,
  (video['id'], video['channel-id'], video['title'], video['description'], video['date-published']))
