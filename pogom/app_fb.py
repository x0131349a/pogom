# -*- coding: utf-8 -*-
from . import config
from .app import Pogom
from .utils import get_pokemon_id
from flask import request
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
        return "ok", 200

    def notify(self, pokemon_list):
        for recipient, notify_when_found in self._fb_subscribers.iteritems():
            for msg, map_link in self._generate_notify_msg(recipient, notify_when_found, pokemon_list):
                fb_send_message(recipient, msg)
                fb_send_message(recipient, img_url=map_link)

    def _generate_notify_msg(self, recipient, notify_list, pokemon_list):
        for m in pokemon_list:
            if m["pokemon_id"] not in notify_list:
                continue
            if m["encounter_id"] not in self._fb_noti_history[recipient]:
                self._fb_noti_history[recipient][m["encounter_id"]] = m['disappear_time']
                exp_ctime = "{h}:{m}:{s}".format(
                    h=m['disappear_time'].hour, m=m['disappear_time'].minute,
                    s=m['disappear_time'].second)
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
        def _get_timestamp(dt):
            return (dt - datetime(1970, 1, 1)).total_seconds()
        pass

    def _get_map_snippet(self, longitude, latitude):
        map_url = "http://maps.googleapis.com/maps/api/staticmap?center={latitude},{longitude}&zoom=16&scale=1&size=300x300&maptype=roadmap&format=jpg&visual_refresh=true&markers=size:small%7Ccolor:0xff0000%7Clabel:%7C{latitude},{longitude}"
        return map_url.format(longitude=longitude, latitude=latitude)

    def _init_subscriber(self, s_id):
        self._fb_subscribers[s_id] = []
        self._fb_noti_history[s_id] = {}

    def _subscribe_pokemon(self, s_id, pokemon_id):
        self._fb_subscribers[s_id].append(pokemon_id)
        self._save_subscriber()

    def _unsubscribe(self, s_id):
        del self._fb_subscribers[s_id]
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

    def _message_processor(self, sender_id, msg):
        response_msg = "QQ more"
        if 'forget me' in msg and sender_id in self._fb_subscribers:
            self._unsubscribe(sender_id)
            response_msg = "how sad but I will..."
        elif 'tell me about' in msg:
            if sender_id not in self._fb_subscribers:
                log.debug('got new sub from {0}'.format(sender_id))
                self._init_subscriber(sender_id)
            pokemon_name = msg.split('tell me about')[1].strip()
            pokemon_id = get_pokemon_id(pokemon_name)
            if pokemon_id:
                pokemon_id = int(pokemon_id)
                if pokemon_id not in self._fb_subscribers[sender_id]:
                    self._subscribe_pokemon(sender_id, pokemon_id)
                response_msg = "sure bro"
            else:
                response_msg = u"wat's {0}".format(pokemon_name)
        elif msg.startswith('llist'):
            response_msg = str(self._fb_subscribers)
        fb_send_message(sender_id, response_msg)


def fb_send_message(recipient_id, msg="", img_url=""):
    msg_request = {
        "params": {"access_token": config['FB_TOKEN']},
        "headers": {"Content-Type": "application/json"},

        "data": json.dumps({
            "recipient": {"id": recipient_id},
            "message": {"text": msg} if msg else {'attachment': {'type': 'image', 'payload': {'url': img_url}}}
        })
    }

    r = requests.post("https://graph.facebook.com/v2.6/me/messages", **msg_request)
    if r.status_code != 200:
        log.debug("send message failed: {0}".format(r.status_code))
