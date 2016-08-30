# -*- coding: utf-8 -*-
import logging
import time
from threading import Thread
from .models import Pokemon

log = logging.getLogger(__name__)
log.setLevel(level=10)


class PokePoller(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.daemon = True
        self.name = 'pokemon_poller'
        self.notify = lambda x: None

    def set_callback(self, notify_func):
        self.notify = notify_func

    def run(self):
        while True:
            time.sleep(10)
            try:
                self.notify(Pokemon.get_active())
            except Exception as e:
                log.debug(e)
