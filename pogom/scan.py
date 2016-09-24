#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import math
import time
import collections
import cProfile
import os
import json
import random
from datetime import datetime
from itertools import izip, count
from threading import Thread
from functools import partial

from pgoapi import PGoApi
from pgoapi.utilities import f2i, get_cell_ids, get_pos_by_name
from sys import maxint
from geographiclib.geodesic import Geodesic

from .models import parse_map, parse_encounter, save_encounter
from . import config

log = logging.getLogger(__name__)


class ScanMetrics:
    CONSECUTIVE_MAP_FAILS = 0
    STEPS_COMPLETED = 0
    NUM_STEPS = 1
    LOGGED_IN = 0.0
    LAST_SUCCESSFUL_REQUEST = 0.0
    COMPLETE_SCAN_TIME = 0
    NUM_THREADS = 0
    NUM_ACCOUNTS = 0
    CURRENT_SCAN_PERCENT = 0.0


class Scanner(Thread):

    def __init__(self, scan_config):
        Thread.__init__(self)
        self.daemon = True
        self.name = 'search_thread'

        self.api = PGoApi(config['SIGNATURE_LIB_PATH'])
        self.scan_config = scan_config

    def next_position(self):
        for point in self.scan_config.COVER:
            yield (point["lat"], point["lng"], 0)

    def callback_encounter(self, response_dict, pokemon_dict):
        if (not response_dict) or ('responses' in response_dict and not response_dict['responses']):
            log.info('Encounter Fetch Failed. Skip...')
            save_encounter(pokemon_dict)
            return
        try:
            parse_encounter(response_dict, pokemon_dict)
        except Exception as e:  # dont crash plz
            log.error(e)
            log.error('Unexpected error while parsing encounter.')
            log.error('Response dict: {}'.format(response_dict))

    def callback(self, response_dict):
        if (not response_dict) or ('responses' in response_dict and not response_dict['responses']):
            log.info('Map Download failed. Trying again.')
            ScanMetrics.CONSECUTIVE_MAP_FAILS += 1
            return

        try:
            pokemons_need_detail = parse_map(response_dict, self.scan_config.DETAIL_POKEMON_LIST)
            for e_id, p_detail in pokemons_need_detail.iteritems():
                self.api.encounter(
                    encounter_id=e_id,
                    spawn_point_id=p_detail['spawnpoint_id'],
                    player_latitude=f2i(p_detail['latitude']),
                    player_longitude=f2i(p_detail['longitude']),
                    position=(p_detail['latitude'], p_detail['longitude'], 0),
                    callback=partial(self.callback_encounter, pokemon_dict=p_detail),
                    priority=2.0
                )

            ScanMetrics.LAST_SUCCESSFUL_REQUEST = time.time()
            ScanMetrics.CONSECUTIVE_MAP_FAILS = 0
            log.debug("Parsed & saved.")
        except Exception as e:  # make sure we dont crash in the main loop
            log.error(e)
            log.error('Unexpected error while parsing response.')
            log.error('Response dict: {}'.format(response_dict))
            ScanMetrics.CONSECUTIVE_MAP_FAILS += 1
        else:
            ScanMetrics.STEPS_COMPLETED += 1
            if ScanMetrics.NUM_STEPS:
                ScanMetrics.CURRENT_SCAN_PERCENT = float(ScanMetrics.STEPS_COMPLETED) / ScanMetrics.NUM_STEPS * 100
            else:
                ScanMetrics.CURRENT_SCAN_PERCENT = 0
            log.info('Completed {:5.2f}% of scan.'.format(ScanMetrics.CURRENT_SCAN_PERCENT))

    def scan(self):
        ScanMetrics.NUM_STEPS = len(self.scan_config.COVER)
        log.info("Starting scan of {} locations".format(ScanMetrics.NUM_STEPS))

        for i, next_pos in enumerate(self.next_position()):
            log.debug('Scanning step {:d} of {:d}.'.format(i, ScanMetrics.NUM_STEPS))
            log.debug('Scan location is {:f}, {:f}'.format(next_pos[0], next_pos[1]))

            # TODO: Add error throttle

            cell_ids = get_cell_ids(next_pos[0], next_pos[1], radius=70)
            timestamps = [0, ] * len(cell_ids)
            self.api.get_map_objects(
                latitude=f2i(next_pos[0]),
                longitude=f2i(next_pos[1]),
                cell_id=cell_ids,
                since_timestamp_ms=timestamps,
                position=next_pos,
                callback=self.callback)

        while not self.api.is_work_queue_empty():
            # Location change
            if self.scan_config.RESTART:
                log.info("Restarting scan")
                self.api.empty_work_queue()
            else:
                time.sleep(2)

        #self.api.wait_until_done()  # Work queue empty != work done

    def run(self):
        while True:
            if self.scan_config.RESTART:
                self.scan_config.RESTART = False
                if self.scan_config.ACCOUNTS_CHANGED:
                    self.scan_config.ACCOUNTS_CHANGED = False
                    num_workers = min(max(int(math.ceil(len(config['ACCOUNTS']) / 23.0)), 3), 10)
                    self.api.resize_workers(num_workers)
                    self.api.add_accounts(config['ACCOUNTS'])

                    ScanMetrics.NUM_THREADS = num_workers
                    ScanMetrics.NUM_ACCOUNTS = len(config['ACCOUNTS'])

            if (not self.scan_config.SCAN_LOCATIONS or
                    not config.get('ACCOUNTS', None)):
                time.sleep(5)
                continue
            ScanMetrics.STEPS_COMPLETED = 0
            scan_start_time = time.time()
            self.scan()
            ScanMetrics.COMPLETE_SCAN_TIME = time.time() - scan_start_time


class ScanConfig(object):
    SCAN_LOCATIONS = {}
    COVER = None

    RESTART = True  # Triggered when the setup is changed due to user input
    ACCOUNTS_CHANGED = True

    DETAIL_POKEMON_LIST = []

    def update_scan_locations(self, scan_locations):
        location_names = set([])
        # Add new locations
        for scan_location in scan_locations:
            if scan_location['location'] not in self.SCAN_LOCATIONS:
                if ('latitude' not in scan_location or
                        'longitude' not in scan_location or
                        'altitude' not in scan_location):
                    lat, lng, alt = get_pos_by_name(scan_location['location'])
                    log.info('Parsed location is: {:.4f}/{:.4f}/{:.4f} '
                             '(lat/lng/alt)'.format(lat, lng, alt))
                    scan_location['latitude'] = lat
                    scan_location['longitude'] = lng
                    scan_location['altitude'] = alt
                self.SCAN_LOCATIONS[scan_location['location']] = scan_location
            location_names.add(scan_location['location'])

        # Remove old locations
        for location_name in self.SCAN_LOCATIONS:
            if location_name not in location_names:
                del self.SCAN_LOCATIONS[location_name]

        self._update_cover()

    def add_scan_location(self, lat, lng, radius):
        scan_location = {
            'location': '{},{}'.format(lat, lng),
            'latitude': lat,
            'longitude': lng,
            'altitude': 0,
            'radius': radius
        }

        self.SCAN_LOCATIONS[scan_location['location']] = scan_location
        self._update_cover()

    def delete_scan_location(self, lat, lng):
        for k, v in self.SCAN_LOCATIONS.iteritems():
            if v['latitude'] == lat and v['longitude'] == lng:
                del self.SCAN_LOCATIONS[k]
                self._update_cover()
                return

    def update_pokemon_list_to_query(self, new_list):
        self.DETAIL_POKEMON_LIST = new_list

    def _update_cover(self):
        cover = []

        # Go backwards through locations so that last location
        # will be scanned first
        for scan_location in reversed(self.SCAN_LOCATIONS.values()):
            lat = scan_location["latitude"]
            lng = scan_location["longitude"]
            radius = scan_location["radius"]

            d = math.sqrt(3) * 70
            points = [[{'lat2': lat, 'lon2': lng, 's': 0}]]

            # The lines below are magic. Don't touch them.
            for i in xrange(1, maxint):
                oor_counter = 0

                points.append([])
                for j in range(0, 6 * i):
                    p = points[i - 1][(j - j / i - 1 + (j % i == 0))]
                    p_new = Geodesic.WGS84.Direct(p['lat2'], p['lon2'], (j+i-1)/i * 60, d)
                    p_new['s'] = Geodesic.WGS84.Inverse(p_new['lat2'], p_new['lon2'], lat, lng)['s12']
                    points[i].append(p_new)

                    if p_new['s'] > radius:
                        oor_counter += 1

                if oor_counter == 6 * i:
                    break

            cover.extend({"lat": p['lat2'], "lng": p['lon2']}
                         for sublist in points for p in sublist if p['s'] < radius)

        self.COVER = cover
