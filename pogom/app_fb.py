from . import config
from .app import Pogom
from .utils import get_pokemon_id
from flask import request
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
        self._fb_subscribers = config['FB_SUBSCRIBERS'] or {}

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
                    self._message_processor(
                        event["sender"]["id"],
                        event["message"]["text"])
        return "ok", 200

    def notify(self, pokemon_list):
        log.debug(pokemon_list)
        for recipient, notify_when_found in self._fb_subscribers.iteritems():
            for m in pokemon_list:
                if m in notify_when_found:
                    fb_send_message(recipient, "{0} is shown and he's going to fuck you".format(m))

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
            del self._fb_subscribers[sender_id]
            self._save_subscriber()
            response_msg = "how sad but I will..."
        elif 'tell me about' in msg:
            if sender_id not in self._fb_subscribers:
                self._fb_subscribers[sender_id] = []
            pokemon_name = msg.split('tell me about')[1].strip()
            pokemon_id = get_pokemon_id(pokemon_name)
            if pokemon_id:
                if pokemon_id not in self._fb_subscribers[sender_id]:
                    self._fb_subscribers[sender_id].append(pokemon_id)
                    self._save_subscriber()
                response_msg = "sure bro"
            else:
                response_msg = u"wat's {0}".format(pokemon_name)
        elif msg.startswith('llist'):
            response_msg = str(self._fb_subscribers.items())
        fb_send_message(sender_id, response_msg)


def fb_send_message(recipient_id, msg):
    msg_request = {
        "params": {"access_token": config['FB_TOKEN']},
        "headers": {"Content-Type": "application/json"},

        "data": json.dumps({
            "recipient": {"id": recipient_id},
            "message": {"text": msg}
        })
    }

    r = requests.post("https://graph.facebook.com/v2.6/me/messages", **msg_request)
    if r.status_code != 200:
        log.debug("send message failed: {0}".format(r.status_code))
