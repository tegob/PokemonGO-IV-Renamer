#!/usr/bin/env python
# coding=utf-8

import argparse
import json
import pogotransfercalc
import random
import re
import requests
import time
from itertools import groupby
from pgoapi import PGoApi
from pgoapi import utilities as util
from pogocpm2level import cpm2level
from random import uniform
from terminaltables import SingleTable

def format_number(num):
	return '{:,}'.format(num)

class Renamer(object):

	def __init__(self):
		self.pokemon = []
		self.api = None
		self.config = None
		self.pokemon_list = None

	def init_config(self):
		parser = argparse.ArgumentParser()
		parser.add_argument('-a', '--auth-service')
		parser.add_argument('-u', '--username')
		parser.add_argument('-p', '--password')
		parser.add_argument('--hash-key', required=True)
		parser.add_argument('--clear', action='store_true', default=False)
		parser.add_argument('--rename', action='store_true', default=False)
		parser.add_argument('--format', default='%percent% %atk %def %sta')
		parser.add_argument('--transfer', action='store_true', default=False)
		parser.add_argument('--locale', default='en')
		parser.add_argument('--location', required=True)
		parser.add_argument('--min-delay', type=int, default=10)
		parser.add_argument('--max-delay', type=int, default=20)
		parser.add_argument('--iv', type=int, default=75)

		self.config = parser.parse_args()
		self.config.overwrite = True

	def start(self):
		self.init_config()

		try:
			self.pokemon_list = json.load(open('locales/pokemon.' + self.config.locale + '.json'))
		except IOError:
			print 'The selected language is currently not supported'
			exit(0)

		self.setup_api()
		self.get_pokemon()
		self.print_pokemon()

		if self.config.clear:
			self.clear_pokemon()
		elif self.config.rename:
			self.rename_pokemon()
		elif self.config.transfer:
			self.transfer_pokemon()

	def get_elevation_for_position(self):
		try:
			url = 'https://maps.googleapis.com/maps/api/elevation/json?locations={},{}'.format(
				str(self.position[0]), str(self.position[1]))
			altitude = requests.get(url).json()[u'results'][0][u'elevation'] + random.uniform(0.9, 1.7)
			print "Local altitude is: {0}m".format(altitude)
			self.position = (self.position[0], self.position[1], altitude)
		except requests.exceptions.RequestException:
			print "Unable to retrieve altitude from Google APIs; setting to 0"

	def get_location(self):
		# use lat/lng directly if matches such a pattern
		prog = re.compile("^(\-?\d+\.\d+),?\s?(\-?\d+\.\d+)$")
		res = prog.match(self.config.location)
		if res:
			print "Using coordinates from CLI directly..."
			self.position = (float(res.group(1)), float(res.group(2)), 0)
		else:
			print "Looking up coordinates using API..."
			self.position = util.get_pos_by_name(self.config.location)

		self.get_elevation_for_position()

	def setup_api(self):
		self.api = PGoApi()
		self.api.activate_hash_server(self.config.hash_key)
		self.get_location()
		print u'Signing in…'
		if not self.api.login(
			self.config.auth_service,
			self.config.username,
			self.config.password,
			self.position[0], # latitude
			self.position[1], # longitude
			self.position[2]  # altitude
			):
			print 'Login error'
			exit(0)

	def wait_randomly(self):
		random_delay = uniform(self.config.min_delay, self.config.max_delay)
		print u'Waiting %.3f seconds…' % random_delay
		time.sleep(random_delay)

	def get_pokemon(self):
		print u'Getting Pokémon list…'
		response_dict = self.api.get_inventory()

		self.pokemon = []
		self.candy = { i: 0 for i in range(1, 251 + 1) }
		inventory_items = (response_dict
			.get('responses', {})
			.get('GET_INVENTORY', {})
			.get('inventory_delta', {})
			.get('inventory_items', {}))

		for item in inventory_items:
			try:
				reduce(dict.__getitem__, ['inventory_item_data', 'candy'], item)
			except KeyError:
				pass
			else:
				candy = item['inventory_item_data']['candy']
				pokedex_number = candy['family_id']
				self.candy[pokedex_number] = candy.get('candy', 0)

		for item in inventory_items:
			try:
				reduce(dict.__getitem__, ['inventory_item_data', 'pokemon_data'], item)
			except KeyError:
				pass
			else:
				try:
					pokemon = item['inventory_item_data']['pokemon_data']

					pid = pokemon['id']
					pokedex_number = pokemon['pokemon_id']
					name = self.pokemon_list[str(pokedex_number)]

					attack = pokemon.get('individual_attack', 0)
					defense = pokemon.get('individual_defense', 0)
					stamina = pokemon.get('individual_stamina', 0)
					iv_percent = int(round((attack + defense + stamina) / 45.0 * 100.0))
					is_favorite = pokemon.get('favorite', 0) > 0

					nickname = pokemon.get('nickname', 'NONE')
					combat_power = pokemon.get('cp', 0)

					cpm = pokemon['cp_multiplier'] + pokemon.get('additional_cp_multiplier', 0)
					level = cpm2level(cpm)

					# https://github.com/AeonLucid/POGOProtos/blob/master/src/POGOProtos/Enums/Gender.proto
					GENDERS = {
						0: '', # unset
						1: u'♂', # male
						2: u'♀', # female
						3: '' # genderless
					}
					gender = GENDERS.get(
						pokemon.get('pokemon_display', {}).get('gender', 0),
						''
					)
					# https://github.com/AeonLucid/POGOProtos/blob/master/src/POGOProtos/Enums/Costume.proto
					has_costume = pokemon.get('pokemon_display', {}).get('costume', 0) > 0

					is_shiny = pokemon.get('pokemon_display', {}).get('shiny', 0) > 0

					self.pokemon.append({
						'id': pid,
						'pokedex_number': pokedex_number,
						'name': name,
						'nickname': nickname,
						'level': level,
						'cp': combat_power,
						'attack': attack,
						'defense': defense,
						'stamina': stamina,
						'iv_percent': iv_percent,
						'is_favorite': is_favorite,
						'move_1': pokemon['move_1'],
						'move_2': pokemon['move_2'],
						'gender': gender,
						'has_costume': has_costume,
						'is_shiny': is_shiny,
					})
				except KeyError:
					pass
		# Sort the way the in-game `Number` option would, i.e. by Pokedex number
		# in ascending order and then by CP in descending order.
		self.pokemon.sort(key=lambda k: (k['pokedex_number'], -k['cp']))

	def print_pokemon(self):
		sorted_mons = sorted(self.pokemon, key=lambda k: (k['pokedex_number'], -k['iv_percent']))
		groups = groupby(sorted_mons, key=lambda k: k['pokedex_number'])
		table_data = [
			[u'Pokémon', 'Level', 'CP', 'IV %', 'ATK', 'DEF', 'STA', 'Candy', 'Recommendation']
		]
		total_evolutions = 0
		total_transfers = 0
		print u'%d Pokémon found.' % len(sorted_mons)
		for key, group in groups:
			group = list(group)
			pokemon_name = self.pokemon_list[str(key)]
			best_iv_pokemon = max(group, key=lambda k: k['iv_percent'])
			best_iv_pokemon['best_iv'] = True
			candy_count=self.candy[key]
			result = pogotransfercalc.calculate(
				pokemon_count=len(group),
				candy_count=candy_count,
				pokedex_number=key)
			evolutions = result['evolutions']
			total_evolutions += evolutions
			if evolutions:
				for pokemon in group[:evolutions]:
					pokemon['message'] = 'evolve'
			transfers = result['transfers']
			transfer_count = 0
			if transfers:
				for pokemon in reversed(group[evolutions:]):
					if pokemon['is_favorite']:
						pokemon['message'] = u'keep (★)'
						continue
					if pokemon['has_costume']:
						pokemon['message'] = u'keep (costume)'
						continue
					if pokemon['is_shiny']:
						pokemon['message'] = u'keep (shiny)'
						continue
					if pokemon['iv_percent'] < self.config.iv:
						pokemon['message'] = 'transfer'
						pokemon['transfer'] = True
						transfer_count += 1
						total_transfers += 1
						if transfer_count == transfers:
							break
						continue
			for pokemon in group:
				if pokemon['iv_percent'] >= self.config.iv:
					iv_msg = u'(IV ≥ %d%%)' % self.config.iv
					if 'message' in pokemon:
						pokemon['message'] += ' %s' % iv_msg
					else:
						pokemon['message'] = 'keep %s' % iv_msg
				row_data = [
					pokemon_name + pokemon['gender'] + (u'✨' if pokemon['is_shiny'] else '') + (u'☃' if pokemon['has_costume'] else '') + (u'★' if pokemon['is_favorite'] else ''),
					pokemon['level'],
					pokemon['cp'],
					'{0:.0f}%'.format(pokemon['iv_percent']),
					pokemon['attack'],
					pokemon['defense'],
					pokemon['stamina'],
					candy_count,
					pokemon.get('message', '')
				]
				table_data.append(row_data)
		table = SingleTable(table_data)
		table.justify_columns = {
			0: 'left', 1: 'right', 2: 'right', 3: 'right',
			4: 'right', 5: 'right', 6: 'right', 7: 'right'
		}
		print table.table
		table = SingleTable([
			['Total suggested transfers', format_number(total_transfers)],
			['Total evolutions', format_number(total_evolutions)],
			['Total XP from evolutions', format_number(total_evolutions * 500)],
			['Total XP from evolutions with lucky egg', format_number(total_evolutions * 1000)],
		])
		table.inner_heading_row_border = False
		table.justify_columns = { 0: 'left', 1: 'right' }
		print table.table

	def rename_pokemon(self):
		already_renamed = 0
		renamed = 0

		# After logging in, wait a while before starting to rename Pokémon, like a
		# human player would.
		self.wait_randomly()

		for pokemon in self.pokemon:
			individual_value = pokemon['attack'] + pokemon['defense'] + pokemon['stamina']
			iv_percent = pokemon['iv_percent']

			if individual_value < 10:
				individual_value = '0' + str(individual_value)

			pokedex_number = pokemon['pokedex_number']
			pokemon_name = self.pokemon_list[str(pokedex_number)]

			name = self.config.format
			name = name.replace('%id', str(pokedex_number))
			name = name.replace('%ivsum', str(individual_value))
			name = name.replace('%atk', str(pokemon['attack']))
			name = name.replace('%def', str(pokemon['defense']))
			name = name.replace('%sta', str(pokemon['stamina']))
			name = name.replace('%percent', str(iv_percent))
			name = name.replace('%cp', str(pokemon['cp']))
			name = name.replace('%name', pokemon_name)
			name = name[:12]

			if (pokemon['nickname'] == 'NONE' \
				or pokemon['nickname'] == pokemon_name \
				or (pokemon['nickname'] != name and self.config.overwrite)) \
				and iv_percent >= self.config.iv:

				response = self.api.nickname_pokemon(pokemon_id=pokemon['id'], nickname=name)

				result = response['responses']['NICKNAME_POKEMON']['result']

				if result == 1:
					print 'Renaming ' + pokemon_name + ' (CP ' + str(pokemon['cp'])  + ') to ' + name
				else:
					print 'Something went wrong with renaming ' + pokemon_name + ' (CP ' + str(pokemon['cp'])  + ') to ' + name + '. Error code: ' + str(result)

				self.wait_randomly()

				renamed += 1

			else:
				already_renamed += 1

		print str(renamed) + ' Pokémon renamed.'
		print str(already_renamed) + ' Pokémon already renamed.'

	def clear_pokemon(self):
		# Reset all Pokémon names to the original name.
		cleared = 0

		# After logging in, wait a while before starting to rename Pokémon, like a
		# human player would.
		self.wait_randomly()

		for pokemon in self.pokemon:
			pokedex_number = pokemon['pokedex_number']
			name_original = self.pokemon_list[str(pokedex_number)]

			if pokemon['nickname'] != 'NONE' and pokemon['nickname'] != name_original:
				response = self.api.nickname_pokemon(pokemon_id=pokemon['id'], nickname=name_original)

				result = response['responses']['NICKNAME_POKEMON']['result']

				if result == 1:
					print 'Reset ' + pokemon['nickname'] +  ' to ' + name_original
				else:
					print 'Something went wrong with resetting ' + pokemon['nickname'] + ' to ' + name_original + '. Error code: ' + str(result)

				self.wait_randomly()

				cleared += 1

		print 'Cleared ' + str(cleared) + ' nicknames'

	def transfer_pokemon(self):
		pokemon_list = [p for p in self.pokemon if p.get('transfer', False) and not p['is_favorite'] and not p['is_shiny'] and not p['has_costume']]
		total_transfers = len(pokemon_list)
		transfers_completed = 0
		if not pokemon_list:
			print u'No Pokémon scheduled to transfer.'
			return
		table_data = [
			[u'Pokémon', 'CP', 'IV %', 'ATK', 'DEF', 'STA']
		]
		print 'About to transfer %d Pokémon…' % total_transfers

		transfer_list = []
		for pokemon in pokemon_list:
			# Remove the Pokémon from the list, so that we don’t try to rename
			# it later.
			self.pokemon.remove(pokemon)

			pokedex_number = pokemon['pokedex_number']
			pokemon_name = self.pokemon_list[str(pokedex_number)]

			table_data.append([
				pokemon_name,
				pokemon['cp'],
				'{0:.0f}%'.format(pokemon['iv_percent']),
				pokemon['attack'],
				pokemon['defense'],
				pokemon['stamina']
			])

			transfer_list.append(pokemon['id'])

		table = SingleTable(table_data)
		table.justify_columns = {
			0: 'left', 1: 'right', 2: 'right', 3: 'right',
			4: 'right', 5: 'right', 6: 'left'
		}
		print u'The following Pokémon are about to be transferred:'
		print table.table

		# After logging in, wait a while before starting to rename Pokémon, like a
		# human player would.
		self.config.min_delay = total_transfers * 2
		self.config.max_delay = total_transfers * 4
		self.wait_randomly()
		response = self.api.release_pokemon(pokemon_ids=transfer_list)
		try:
			result = response['responses']['RELEASE_POKEMON']['result']
		except KeyError:
			print 'Failed:'
			print response
			status = 'error'
			pass
		else:
			if result == 1:
				status = 'success'
				print 'Transfer successful.'
			else:
				status = 'error'
				print 'Transfer failed. Error code: %s' % str(result)

if __name__ == '__main__':
	Renamer().start()
