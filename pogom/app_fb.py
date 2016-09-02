# -*- coding: utf-8 -*-
from __future__ import division
from . import config
from .app import Pogom
from .utils import get_pokemon_id, get_pokemon_names, get_pokemon_name
from flask import request
from pytz import timezone
from datetime import datetime
from time import time
import logging
import requests
import json
import os

log = logging.getLogger(__name__)
log.setLevel(level=10)


class PogomFb(Pogom):

    def __init__(self, *args, **kwargs):
        super(PogomFb, self).__init__(*args, **kwargs)
        self.route('/fb', methods=['POST'])(self.message_handler)
        self.route('/fb', methods=['GET'])(self.verify)
        # move to model or somewhere
        self._timezone = timezone(config['FB_NOTIFICATION_TIMEZONE'] or 'UTC')
        self._fb_subscribers = config['FB_SUBSCRIBERS'] or {}
        self._fb_noti_history = {}
        for subscriber in self._fb_subscribers.iterkeys():
            self._fb_noti_history[subscriber] = {}

    def verify(self):
        log.info('')
        if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
            if request.args.get("hub.verify_token") == config['FB_VERIFICATION_CODE']:
                return request.args["hub.challenge"], 200
            else:
                return "verification failed", 403
        return "bad request", 400

    def message_handler(self):
        data = request.get_json()
        log.debug('Got msg from fb:{0}'.format(data))

        if data["object"] == "page":
            for entry in data["entry"]:
                for event in entry["messaging"]:
                    if "message" not in event:
                        continue
                    if "text" in event["message"]:
                        self._message_processor(
                            event["sender"]["id"],
                            event["message"]["text"])
                    if "attachments" in event["message"]:
                        for attachment in event["message"]["attachments"]:
                            if attachment.get("type") == "location":
                                coord = attachment["payload"]["coordinates"]
                                self._location_processor(
                                    sender_id=event["sender"]["id"],
                                    lat=coord["lat"], lng=coord["long"])
        return "ok", 200

    def notify(self, pokemon_list):
        for recipient, subscriber_info in self._fb_subscribers.iteritems():
            notify_when_found = subscriber_info['subscription']
            for msg, map_link in self._generate_notify_msg(recipient, notify_when_found, pokemon_list):
                fb_send_message(recipient, img_url=map_link)
                fb_send_message(recipient, msg)

    def _add_map_location(self, lat, lng, radius):
        if all((lat, lng, radius)):
            self.scan_config.add_scan_location(lat, lng, radius)

    def _del_map_location(self, lat, lng):
        if all((lat, lng)):
            self.scan_config.delete_scan_location(lat, lng)

    def _get_timestamp(self, dt):
        return (dt - datetime(1970, 1, 1)).total_seconds()

    def _generate_notify_msg(self, recipient, notify_list, pokemon_list):
        for m in pokemon_list:
            if m["pokemon_id"] not in notify_list:
                continue
            if m["encounter_id"] not in self._fb_noti_history[recipient]:
                # normalize time
                disappear_ts = self._get_timestamp(m['disappear_time'])
                self._fb_noti_history[recipient][m["encounter_id"]] = disappear_ts
                local_time = datetime.fromtimestamp(disappear_ts, self._timezone)
                exp_ctime = "{h:0>2}:{m:0>2}:{s:0>2}".format(
                    h=local_time.hour, m=local_time.minute,
                    s=local_time.second)
                msg = (
                    u"野生的 {pokemon_name} 出現了!",
                    u"消失於: {ctime}"
                )
                msg = u"\n".join(msg)
                msg = msg.format(
                    pokemon_name=m['pokemon_name'],
                    ctime=exp_ctime
                )
                yield (
                    msg,
                    self._get_map_snippet(longitude=m['longitude'], latitude=m['latitude'])
                )

    def _clear_expired_entries_from_history(self):
        pass

    def _get_map_snippet(self, longitude, latitude):
        map_url = "http://maps.googleapis.com/maps/api/staticmap?center={latitude},{longitude}&zoom=16&scale=1&size=300x300&maptype=roadmap&format=jpg&visual_refresh=true&markers=size:small%7Ccolor:0xff0000%7Clabel:%7C{latitude},{longitude}"
        return map_url.format(longitude=longitude, latitude=latitude)

    def _init_subscriber(self, s_id):
        self._fb_subscribers[s_id] = {}
        self._fb_subscribers[s_id]['subscription'] = []
        self._fb_subscribers[s_id]['recon'] = None
        self._fb_noti_history[s_id] = {}

    def _subscribe_pokemon(self, s_id, pokemon_id):
        if pokemon_id not in self._fb_subscribers[s_id]['subscription']:
            self._fb_subscribers[s_id]['subscription'].append(pokemon_id)
            self._save_subscriber()
            return "sure bro"
        else:
            return "u said"

    def _unsubscribe_pokemon(self, s_id, pokemon_id):
        if pokemon_id in self._fb_subscribers[s_id]['subscription']:
            self._fb_subscribers[s_id]['subscription'].remove(pokemon_id)
            self._save_subscriber()
            return "If this is what you want..."
        else:
            return "never heard that!"

    def _get_subscription_list(self, s_id):
        if s_id in self._fb_subscribers:
            return " ".join([get_pokemon_name(n) for n in self._fb_subscribers[s_id]['subscription']])
        else:
            return ""

    def _unsubscribe_all(self, s_id):
        if s_id in self._fb_subscribers:
            self._del_subscriber_location[s_id]
            del self._fb_subscribers[s_id]
        if s_id in self._fb_noti_history:
            del self._fb_noti_history[s_id]
        self._save_subscriber()

    def _save_subscriber(self):
        if (config['CONFIG_PATH'] is not None and os.path.isfile(config['CONFIG_PATH'])):
            config_path = config['CONFIG_PATH']
        else:
            config_path = os.path.join(config['ROOT_PATH'], 'config.json')

        data = json.load(open(config_path, 'r'))
        data['FB_SUBSCRIBERS'] = self._fb_subscribers
        with open(config_path, 'w') as f:
            f.write(json.dumps(data))

    def _move_subscriber_location(self, s_id, lat, lng):
        self._del_subscriber_location(s_id)
        self._add_map_location(lat, lng, 200)
        self._fb_subscribers[s_id]['recon'] = (lat, lng)
        self._save_subscriber()

    def _del_subscriber_location(self, s_id):
        if self._fb_subscribers[s_id]['recon']:
            prev_lat, prev_lng = self._fb_subscribers[s_id]['recon']
            self._del_map_location(prev_lat, prev_lng)
            self._fb_subscribers[s_id]['recon'] = None

    def _location_processor(self, sender_id, lat, lng):
        if sender_id not in self._fb_subscribers:
            self._init_subscriber(sender_id)
        self._move_subscriber_location(sender_id, lat, lng)
        fb_send_message(sender_id, "delivering ur pizzzaa")

    def _message_processor(self, sender_id, msg):
        response_msg = "QQ more"
        if 'forget me' in msg:
            self._unsubscribe_all(sender_id)
            response_msg = "how sad but I will..."
        elif msg.startswith('byebye') or msg.startswith('tell me about'):
            if sender_id not in self._fb_subscribers:
                self._init_subscriber(sender_id)
            if 'byebye' in msg:
                splitter = 'byebye'
                func = self._unsubscribe_pokemon
            else:
                splitter = 'tell me about'
                func = self._subscribe_pokemon
            pokemon_name = msg.split(splitter)[1].strip()
            pokemon_id = get_pokemon_id(pokemon_name)
            if pokemon_id:
                pokemon_id = int(pokemon_id)
                response_msg = func(sender_id, pokemon_id)
            else:
                response_msg = u"wat's {0}".format(pokemon_name)
        elif msg.startswith('what did i say'):
            response_msg = self._get_subscription_list(sender_id)
            if not response_msg:
                response_msg = 'i know nothing about you, tell me more'
        elif msg.startswith('cancel my flight'):
            self._del_subscriber_location(sender_id)
            self._save_subscriber()
            response_msg = 'oh...'
        elif msg.startswith('pokedex'):
            response_msg = " ".join(get_pokemon_names())
        elif msg.startswith('llist'):
            # for debug
            response_msg = str(self._fb_subscribers[sender_id])
        fb_send_message(sender_id, response_msg)


def fb_send_message(recipient_id, msg="", img_url=""):
    def _send():
        msg_request = {
            "params": {"access_token": config['FB_TOKEN']},
            "headers": {"Content-Type": "application/json"},

            "data": json.dumps({
                "recipient": {"id": recipient_id},
                "message": {"text": msg_seg} if msg_seg else {'attachment': {'type': 'image', 'payload': {'url': img_url}}}
            })
        }

        r = requests.post("https://graph.facebook.com/v2.6/me/messages", **msg_request)
        if r.status_code != 200:
            log.debug("send message failed: {0}".format(r.status_code))

    seg_size = 120
    if len(msg) > seg_size:
        segs = len(msg) // seg_size
        i = 0
        for i in xrange(1, segs + 1):
            msg_seg = msg[(i - 1) * seg_size:i * seg_size]
            _send()
        if len(msg) % seg_size != 0:
            msg_seg = msg[i * seg_size:]
            _send()
    else:
        msg_seg = msg
        _send()
