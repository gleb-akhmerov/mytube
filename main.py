import datetime
import re
import sqlite3
from threading import Thread
from urllib import request

from bs4 import BeautifulSoup
import flask
from lxml.builder import E
from lxml import etree

import youtube


def page(title, *body):
  html = E.html(
    {'lang': 'en'},
    E.head(
      E.meta(charset='UTF-8'),
      E.meta(name='viewport', content='width=device-width, initial-scale=1.0'),
      E.title(title),
      E.link(rel='stylesheet', type='text/css', href='/style.css'),
    ),
    E.body(
      E.div(
        {'class': 'header'},
        E.a('Home', href='/'),
        E.a('Channels', href='/subscriptions'),
        E.a('Random', href='/shuffle'),
      ),
      *body
    )
  )
  return etree.tostring(html, encoding=str, doctype="<!DOCTYPE html>")


def page_latest_videos(conn, page_number):
  records = conn.execute("""
    select
      Video.id,
      Video.title,
      Channel.id as channel_id,
      Channel.name as channel_name
    from
      Video
    join Channel
      on Channel.id = Video.channel_id
    order by
      Video.date
      desc
    limit
      25
    offset
      ?
  """,
  (24 * (page_number - 1),)).fetchall()

  return page("YouTube Videos",
    E.div(
      {'class': 'gallery'},
      *[E.div(
          *html_video_link(r['id'], r['title']),
          E.a(
            {'class': 'channel-link'},
            E.div({'class': 'channel'}, r['channel_name']),
            href='/channel/' + r['channel_id']
          ),
        )
        for r in records[:24]]
    ),
    *([E.a('Previous Page', href=f'/{page_number - 1}')] if page_number > 1 else []),
    *([E.a('Next Page',     href=f'/{page_number + 1}')] if len(records) == 25 else []),
  )


def page_shuffle(conn):
  records = conn.execute("""
    select
      Video.id,
      Video.title,
      Channel.id as channel_id,
      Channel.name as channel_name
    from
      Video
    join Channel
      on Channel.id = Video.channel_id
    order by
      random()
    limit
      24
  """)

  return page("YouTube Videos",
    E.div(
      {'class': 'gallery'},
      *[E.div(
          *html_video_link(r['id'], r['title']),
          E.a(
            {'class': 'channel-link'},
            E.div({'class': 'channel'}, r['channel_name']),
            href='/channel/' + r['channel_id']
          ),
        )
        for r in records]
    )
  )


def html_video_link(id, title):
  return [
    E.a(
      {'class': 'video-link'},
      E.div({'class': 'thumbnail-div'}, E.img({'class': 'thumbnail'}, src='https://i.ytimg.com/vi/' + id + '/mqdefault.jpg', alt=title)),
      href='vnd.youtube://' + id,
    ),
    E.a(E.div({'class': 'title'}, title), href='/video/' + id),
  ]


def page_channel(conn, id, page_number):
  with conn:
    channel_name = conn.execute('select name from Channel where id = ?', (id,)).fetchone()['name']
    records = conn.execute("""
      select
        id,
        title
      from
        Video
      where
        channel_id = ?
      order by
        date
        desc
      limit
        25
      offset
        ?
    """,
    (id, 24 * (page_number - 1))).fetchall()

  return page(channel_name,
    E.div(
      {'class': 'gallery'},
      *[E.div(*html_video_link(r['id'], r['title']))
        for r in records[:24]]
    ),
    *([E.a('Previous Page', href=f'/channel/{id}/{page_number - 1}')] if page_number > 1 else []),
    *([E.a('Next Page',     href=f'/channel/{id}/{page_number + 1}')] if len(records) == 25 else []),
  )


def page_playlist(conn, id):
  with conn:
    names = conn.execute("""
      select
        Channel.name as channel,
        Playlist.name as playlist
      from
        Playlist
      join Channel
        on Channel.id = Playlist.channel_id
      where
        Playlist.id = ?
    """,
    (id,)).fetchone()
    records = conn.execute("""
      select
        Video.id,
        Video.title
      from
        PlaylistVideo
      join Video
        on Video.id = PlaylistVideo.video_id
      where
        PlaylistVideo.playlist_id = ?
      order by
        PlaylistVideo.playlist_row
    """,
    (id,)).fetchall()

  return page(names['channel'] + ' — ' + names['playlist'],
    E.div(
      {'class': 'gallery'},
      *[E.div(*html_video_link(r['id'], r['title']))
        for r in records]
    )
  )


def page_video(conn, id):
  with conn:
    video = conn.execute('select * from Video where id = ?', (id,)).fetchone()
    records = conn.execute("""
      select
        Playlist.id,
        Playlist.name
      from
        PlaylistVideo
      join Playlist
        on Playlist.id = PlaylistVideo.playlist_id
      where
        PlaylistVideo.video_id = ?
    """,
    (id,)).fetchall()

  return page(video['title'],
    E.div(E.img(src='https://i.ytimg.com/vi/' + id + '/hqdefault.jpg', alt=video['title'])),
    E.div(datetime.datetime.fromtimestamp(video['date']).strftime('%B %-d %Y')),
    E.div("Playlists"),
    *[E.div(E.a(r['name'], href='/playlist/' + r['id'])) for r in records],
  )


def page_channel_playlists(conn, id):
  with conn:
    channel_name = conn.execute('select name from Channel where id = ?', (id,)).fetchone()['name']
    records = conn.execute("""
      select
        Playlist.id,
        Playlist.name,
        PlaylistVideo.video_id
      from
        Playlist
      join PlaylistVideo
        on PlaylistVideo.playlist_id = Playlist.id
      where
        Playlist.channel_id = ?
        and PlaylistVideo.playlist_row = 1
    """,
    (id,)).fetchall()

  return page(channel_name + " Playlists",
    E.div(
      {'class': 'gallery'},
      *[E.div(
          E.a(
            {'class': 'video-link'},
            E.div({'class': 'thumbnail-div'}, E.img({'class': 'thumbnail'}, src='https://i.ytimg.com/vi/' + r['video_id'] + '/mqdefault.jpg', alt=r['name'])),
            E.div({'class': 'title'}, r['name']),
            href='/playlist/' + r['id'],
          ),
        )
        for r in records
      ]
    )
  )


def page_subscriptions(conn):
  channels = conn.execute('select * from Channel order by lower(name)')

  return page("Subscriptions",
    *[E.div(E.a(E.div({'class': 'subscriptions-channel'}, chan['name']), href='/channel/' + chan['id']))
      for chan in channels]
  )


def page_new_subscription():
  return page("Add Subscription",
    E.form(
      E.input(placeholder="Channel URL", name='url', type='text'),
      E.input(value="Add", type='submit'),
      action='/add-subscription/'
    )
  )


def page_add_subscription(conn, channel_url):
  found = re.match('https://www\.youtube\.com/channel/([A-Za-z0-9-_]+)', channel_url)
  if found:
    chan_rss_url = 'https://www.youtube.com/feeds/videos.xml?channel_id=' + found.group(1)
  else:
    found = re.match(r'https://www\.youtube\.com/user/([A-Za-z0-9-_]+)', channel_url)
    chan_rss_url = 'https://www.youtube.com/feeds/videos.xml?user=' + found.group(1)

  with request.urlopen(chan_rss_url, timeout=5) as rss:
    soup = BeautifulSoup(rss, "xml")
  id = soup.find('yt:channelId').string
  name = soup.author.find('name').string

  with conn:
    conn.execute('insert into Channel (id, name) values (?, ?)', (id, name))
    conn.execute('insert into ChannelNeedsVideoSync (id) values (?)', (id,))
    conn.execute('insert into ChannelNeedsPlaylistSync (id) values (?)', (id,))

  return page("Subscription Added",
    "Subscription added."
  )


def page_style_css():
  with open('style.css') as f:
    return flask.Response(f.read(), mimetype='text/css')


def main():
  def connect():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

  Thread(target=lambda: youtube.updater(connect())).start()
  Thread(target=lambda: youtube.load_all_videos(connect())).start()
  Thread(target=lambda: youtube.load_playlists(connect())).start()

  app = flask.Flask(__name__)
  app.add_url_rule('/style.css', 'style_css', page_style_css)
  app.add_url_rule('/', 'index', lambda: page_latest_videos(connect(), 1))
  app.add_url_rule('/<int:page>', 'index-paged', lambda page: page_latest_videos(connect(), page))
  app.add_url_rule('/subscriptions/', 'subscriptions', lambda: page_subscriptions(connect()))
  app.add_url_rule('/channel/<id>/', 'channel', lambda id: page_channel(connect(), id, 1))
  app.add_url_rule('/channel/<id>/<int:page>/', 'channel_paged', lambda id, page: page_channel(connect(), id, int(page)))
  app.add_url_rule('/playlist/<id>/', 'playlist', lambda id: page_playlist(connect(), id))
  app.add_url_rule('/channel-playlists/<id>/', 'channel-playlists', lambda id: page_channel_playlists(connect(), id))
  app.add_url_rule('/video/<id>/', 'video', lambda id: page_video(connect(), id))
  app.add_url_rule('/shuffle/', 'shuffle', lambda: page_shuffle(connect()))
  app.add_url_rule('/new-subscription/', 'new-subscription', page_new_subscription)
  app.add_url_rule('/add-subscription/', 'add-subscription', lambda: page_add_subscription(connect(), flask.request.args.get('url', type = str)))

  try:
    app.run(host='0.0.0.0', port=5000)
  except KeyboardInterrupt:
    conn.close()


if __name__ == '__main__':
  main()
