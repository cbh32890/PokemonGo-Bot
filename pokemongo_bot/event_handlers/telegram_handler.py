# -*- coding: utf-8 -*-
import asyncio
import time
import re
import telegram
from pokemongo_bot.event_manager import EventHandler
from .chat_handler import ChatHandler
from pokemongo_bot.inventory import Pokemons
from pokemongo_bot import inventory
from pokemongo_bot.item_list import Item

DEBUG_ON = False
SUCCESS = 1
ERROR_XP_BOOST_ALREADY_ACTIVE = 3
ERROR_INCENSE_ALREADY_ACTIVE = 2

class TelegramSnipe:
    ENABLED = False
    ID = 0
    POKEMON_NAME = ''
    LATITUDE = 0.0
    LONGITUDE = 0.0
    SNIPE_DISABLED = False

class TelegramClass:
    update_id = None

    def __init__(self, bot, pokemons, config):
        self.bot = bot
        self.config = config
        self.chat_handler = ChatHandler(self.bot, pokemons)
        self.master = self.config.get('master')
        self.pokemons = pokemons
        self._tbot = None

        with self.bot.database as conn:
            initiator = TelegramDBInit(bot.database)
            if str(self.master).isnumeric():
                self.bot.logger.info(f"Telegram master is valid (numeric): {self.master}")
            elif self.master is not None:
                self.bot.logger.info(f"Telegram master is not numeric: {self.master}")
                c = conn.cursor()
                srchmaster = re.sub(r'^@', '', self.master)
                c.execute("SELECT uid FROM telegram_uids WHERE username = ?", (srchmaster,))
                results = c.fetchall()
                if results:
                    self.bot.logger.info(f"Telegram master UID from datastore: {results[0][0]}")
                    self.master = results[0][0]
                else:
                    self.bot.logger.info("Telegram master UID not in datastore yet")

    async def connect(self):
        if DEBUG_ON:
            self.bot.logger.info("Not connected. Reconnecting")
        self._tbot = telegram.Bot(self.bot.config.telegram_token)
        try:
            updates = await self._tbot.get_updates()
            self.update_id = updates[0].update_id if updates else None
        except IndexError:
            self.update_id = None

    def grab_uid(self, update):
        with self.bot.database as conn:
            conn.execute("REPLACE INTO telegram_uids (uid, username) VALUES (?, ?)",
                         (update.message.chat_id, update.message.from_user.username))
            conn.commit()
        if self.master:
            self.master = update.message.chat_id

    def isMasterFromConfigFile(self, chat_id):
        if not hasattr(self, "master") or not self.master:
            return False
        if str(self.master).isnumeric():
            return str(chat_id) == str(self.master)
        else:
            with self.bot.database as conn:
                cur = conn.cursor()
                cur.execute("SELECT username FROM telegram_uids WHERE uid = ?", (chat_id,))
                res = cur.fetchone()
                return res is not None and str(res[0]) == str(re.sub(r'^@', '', self.master))

    def isMasterFromActiveLogins(self, chat_id):
        with self.bot.database as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(1) FROM telegram_logins WHERE uid = ?", (chat_id,))
            res = cur.fetchone()
            return res[0] == 1

    def isAuthenticated(self, chat_id):
        return self.isMasterFromConfigFile(chat_id) or self.isMasterFromActiveLogins(chat_id)

    def deauthenticate(self, update):
        with self.bot.database as conn:
            cur = conn.cursor()
            sql = f"DELETE FROM telegram_logins WHERE uid = {update.message.chat_id}"
            cur.execute(sql)
            conn.commit()
        asyncio.run_coroutine_threadsafe(
            self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text="Logout completed"),
            asyncio.get_event_loop()
        )

    def authenticate(self, update):
        args = update.message.text.split(' ')
        if len(args) != 2:
            asyncio.run_coroutine_threadsafe(
                self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text="Invalid password"),
                asyncio.get_event_loop()
            )
            return
        password = args[1]
        if password != self.config.get('password', None):
            asyncio.run_coroutine_threadsafe(
                self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text="Invalid password"),
                asyncio.get_event_loop()
            )
        else:
            with self.bot.database as conn:
                cur = conn.cursor()
                cur.execute("INSERT OR REPLACE INTO telegram_logins(uid) VALUES(?)", (update.message.chat_id,))
                conn.commit()
            asyncio.run_coroutine_threadsafe(
                self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                 text="Authentication successful, you can now use all commands"),
                asyncio.get_event_loop()
            )

    async def sendMessage(self, chat_id=None, parse_mode='Markdown', text=None):
        try:
            if self._tbot is None:
                await self.connect()
            await self._tbot.send_message(chat_id=chat_id, parse_mode=parse_mode, text=text)
        except telegram.error.NetworkError:
            time.sleep(1)
        except telegram.error.TelegramError:
            time.sleep(10)
        except telegram.error.Unauthorized:
            self.update_id = self.update_id + 1 if self.update_id is not None else 1

    async def sendLocation(self, chat_id, latitude, longitude):
        try:
            await self._tbot.send_location(chat_id=chat_id, latitude=latitude, longitude=longitude)
        except telegram.error.NetworkError:
            time.sleep(1)
        except telegram.error.TelegramError:
            time.sleep(10)
        except telegram.error.Unauthorized:
            self.update_id = self.update_id + 1 if self.update_id is not None else 1

    async def send_player_stats_to_chat(self, chat_id):
        stats = self.chat_handler.get_player_stats()
        if stats:
            await self.sendMessage(
                chat_id=chat_id,
                parse_mode='Markdown',
                text=f"*{stats[0]}* \n_Level:_ {stats[1]} \n_XP:_ {stats[2]}/{stats[3]} \n_Pokemons Captured:_ {stats[4]} ({stats[5]} _last 24h_) \n_Poke Stop Visits:_ {stats[6]} ({stats[7]} _last 24h_) \n_KM Walked:_ {stats[8]} \n_Stardust:_ {stats[9]}"
            )
            await self.sendLocation(chat_id=chat_id, latitude=self.bot.api._position_lat,
                                    longitude=self.bot.api._position_lng)
        else:
            await self.sendMessage(chat_id=chat_id, parse_mode='Markdown', text="Stats not loaded yet\n")

    def send_event(self, event, formatted_msg, data):
        return self.chat_handler.get_event(event, formatted_msg, data)

    async def send_events(self, update):
        events = self.chat_handler.get_events(update)
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='HTML', text="\n".join(events))

    async def send_softbans(self, update, num):
        softbans = self.chat_handler.get_softbans(num)
        outMsg = ''
        if softbans:
            for x in softbans:
                outMsg += f'*{x[0]}* ({x[2]})\n'
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)
        else:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                   text="No Softbans found! Good job!\n")

    async def send_subscription_updated(self, update):
        self.chsub(update.message.text, update.message.chat_id)
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='HTML', text="Subscriptions updated.")

    async def send_info(self, update):
        await self.send_player_stats_to_chat(update.message.chat_id)

    async def send_logout(self, update):
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='HTML', text="Logged out.")
        self.deauthenticate(update)

    async def send_caught(self, update, num, order):
        caught = self.chat_handler.get_caught(num, order)
        outMsg = ''
        if caught:
            for x in caught:
                outMsg += f'*{x[0]}* (_CP:_ {int(x[1])} _IV:_ {x[2]})\n'
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)
        else:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                   text="No Pokemon Caught Yet.\n")

    async def request_snipe(self, update, pkm, location):
        loc_list = location.split(',')
        try:
            id = Pokemons.id_for(pkm)
        except:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text="Invalid Pokemon")
            return

        TelegramSnipe.ENABLED = True
        TelegramSnipe.ID = int(id)
        TelegramSnipe.POKEMON_NAME = str(pkm)
        TelegramSnipe.LATITUDE = float(loc_list[0].strip())
        TelegramSnipe.LONGITUDE = float(loc_list[1].strip())

        outMsg = f'Catching pokemon: {TelegramSnipe.POKEMON_NAME} at Latitude: {TelegramSnipe.LATITUDE} Longitude: {TelegramSnipe.LONGITUDE}\n'
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)

    async def request_snipe_time(self, update, location):
        last_position = self.bot.position[0:2]
        loc_list = location.split(',')
        snipe_distance = convert(distance(last_position[0], last_position[1], float(loc_list[0].strip()), float(loc_list[1].strip())), "m", "km")
        time_to_snipe = wait_time_sec(snipe_distance)
        time_to_snipe_str_min = time.strftime("%M:%S", time.gmtime(time_to_snipe))
        if time_to_snipe <= 900:
            outMsg = f"Estimated Time to Snipe: {time_to_snipe_str_min} Distance: {snipe_distance:.2f}KM"
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)
        else:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                   text="Sniping distance is more than supported distance")

    async def request_snipe_disable(self, update, config):
        TelegramSnipe.SNIPE_DISABLED = config.lower() == "true"
        msg = "Sniper disabled" if TelegramSnipe.SNIPE_DISABLED else "Sniper set as default"
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=msg)
        return TelegramSnipe.SNIPE_DISABLED

    async def send_evolved(self, update, num, order):
        evolved = self.chat_handler.get_evolved(num, order)
        outMsg = ''
        if evolved:
            for x in evolved:
                outMsg += f'*{x[0]}* (_CP:_ {int(x[1])} _IV:_ {x[2]})\n'
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)
        else:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                   text="No Evolutions Found.\n")

    async def request_luckyegg_count(self, update):
        lucky_egg = inventory.items().get(Item.ITEM_LUCKY_EGG.value)
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                              text=f"Lucky Egg Count: {lucky_egg.count}")

    async def request_ordincense_count(self, update):
        ord_incense = inventory.items().get(Item.ITEM_INCENSE_ORDINARY.value)
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                              text=f"Ordinary Incense Count: {ord_incense.count}")

    async def request_luckyegg(self, update):
        lucky_egg = inventory.items().get(Item.ITEM_LUCKY_EGG.value)
        if lucky_egg.count == 0:
            return False

        response_dict = self.bot.use_lucky_egg()
        if not response_dict:
            self.bot.logger.info("Telegram Request: Failed to use lucky egg!")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text="Failed to use lucky egg!\n")
            return False

        result = response_dict.get("responses", {}).get("USE_ITEM_XP_BOOST", {}).get("result", 0)
        if result == SUCCESS:
            lucky_egg.remove(1)
            self.bot.logger.info(f"Telegram Request: Used lucky egg, {lucky_egg.count} left.")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text=f"Used lucky egg, {lucky_egg.count} left.")
            return True
        elif result == ERROR_XP_BOOST_ALREADY_ACTIVE:
            self.bot.logger.info(f"Telegram Request: Lucky egg already active, {lucky_egg.count} left.")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text=f"Lucky egg already active, {lucky_egg.count} left.")
            return True
        else:
            self.bot.logger.info("Telegram Request: Failed to use lucky egg!")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text="Failed to use lucky egg!\n")
            return False

    async def request_ordincense(self, update):
        ord_incense = inventory.items().get(Item.ITEM_INCENSE_ORDINARY.value)
        if ord_incense.count == 0:
            return False

        request = self.bot.api.create_request()
        request.use_incense(incense_type=401)
        response_dict = request.call()
        if not response_dict:
            self.bot.logger.info("Telegram Request: Failed to use ordinary incense!")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text="Failed to use ordinary incense!\n")
            return False

        result = response_dict.get('responses', {}).get('USE_INCENSE', {}).get('result', 0)
        self.bot.logger.info(f"Result = {result}")
        if result == SUCCESS:
            ord_incense.remove(1)
            self.bot.logger.info(f"Telegram Request: Used ordinary incense, {ord_incense.count} left.")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text=f"Used ordinary incense, {ord_incense.count} left.")
            return True
        elif result == ERROR_INCENSE_ALREADY_ACTIVE:
            self.bot.logger.info(f"Telegram Request: Ordinary incense already active, {ord_incense.count} left.")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text=f"Ordinary incense already active, {ord_incense.count} left.")
            return True
        else:
            self.bot.logger.info(f"Telegram Request: Failed to use ordinary incense! Result={result}")
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text="Failed to use ordinary incense!\n")
            return False

    async def request_incensetime(self, update):
        self.bot.logger.info("Time Started")
        currentincense = inventory.applied_items().get('401')
        self.bot.logger.info(currentincense)
        return True

    async def send_pokestops(self, update, num):
        pokestops = self.chat_handler.get_pokestops(num)
        outMsg = ''
        if pokestops:
            for x in pokestops:
                outMsg += f'*{x[0]}* (_XP:_ {x[1]} _Items:_ {x[2]})\n'
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)
        else:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text="No Pokestops Encountered Yet.\n")

    async def send_hatched(self, update, num, order):
        hatched = self.chat_handler.get_hatched(num, order)
        outMsg = ''
        if hatched:
            for x in hatched:
                outMsg += f'*{x[0]}* (_CP:_ {int(x[1])} _IV:_ {x[2]})\n'
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)
        else:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text="No Eggs Hatched Yet.\n")

    async def send_released(self, update, num, order):
        released = self.chat_handler.get_released(num, order)
        outMsg = ''
        if released:
            for x in released:
                outMsg += f'*{x[0]}* (_CP:_ {int(x[1])} _IV:_ {x[2]})\n'
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)
        else:
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                  text="No Pokemon Released Yet.\n")

    async def send_vanished(self, update, num, order):
        vanished = self.chat_handler.get_vanished(num, order)
        outMsg = ''
        if vanished:
            for x in vanished:
                outMsg += f'*{x[0]}* (_CP:_ {int(x[1])} _IV:_ {x[2]})\n'
            await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)

    async def send_top(self, update, num, order):
        top = self.chat_handler.get_top(num, order)
        outMsg = ''
        for x in top:
            outMsg += f"*{x[0]}* _CP:_ {x[1]} _IV:_ {x[2]} (Candy: {x[3]})\n"
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text=outMsg)

    async def showsubs(self, update):
        subs = []
        with self.bot.database as conn:
            for sub in conn.execute("SELECT uid, event_type, parameters FROM telegram_subscriptions WHERE uid = ?",
                                    (update.message.chat_id,)).fetchall():
                subs.append(f"{sub[1]} -&gt; {sub[2]}")
        if not subs:
            subs.append("No subscriptions found. Subscribe using /sub EVENTNAME. For a list of events, send /events")
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='HTML', text="\n".join(subs))

    def chsub(self, msg, chatid):
        cmd, evt, params = self.tokenize(msg, 3)
        sql = (
            "REPLACE INTO telegram_subscriptions(uid, event_type, parameters) VALUES (?, ?, ?)"
            if cmd == "/sub"
            else (
                "DELETE FROM telegram_subscriptions WHERE uid = ? AND (event_type = ? OR parameters = ? OR 1 = 1)"
                if evt == "everything"
                else "DELETE FROM telegram_subscriptions WHERE uid = ? AND event_type = ? AND parameters = ?"
            )
        )
        with self.bot.database as conn:
            conn.execute(sql, (chatid, evt, params))
            conn.commit()

    async def send_start(self, update):
        res = (
            "*Commands: *",
            "/info - info about bot",
            "/login <password> - authenticate with the bot; once authenticated, your ID will be registered with the bot and survive bot restarts",
            "/logout - remove your ID from the 'authenticated' list",
            "/sub <eventName> <parameters> - subscribe to eventName, with optional parameters, event name=all will subscribe to ALL events (LOTS of output!)",
            "/unsub <eventName> <parameters> - unsubscribe from eventName; parameters must match the /sub parameters",
            "/unsub everything - will remove all subscriptions for this uid",
            "/showsubs - show current subscriptions",
            "/events <filter> - show available events, filtered by regular expression <filter>",
            "/top <num> <cp-or-iv-or-dated> - show top X pokemons, sorted by CP, IV, or Date",
            "/evolved <num> <cp-or-iv-or-dated> - show top x pokemon evolved, sorted by CP, IV, or Date",
            "/hatched <num> <cp-or-iv-or-dated> - show top x pokemon hatched, sorted by CP, IV, or Date",
            "/caught <num> <cp-or-iv-or-dated> - show top x pokemon caught, sorted by CP, IV, or Date",
            "/pokestops - show last x pokestops visited",
            "/released <num> <cp-or-iv-or-dated> - show top x released, sorted by CP, IV, or Date",
            "/vanished <num> <cp-or-iv-or-dated> - show top x vanished, sorted by CP, IV, or Date",
            "/snipe <PokemonName> <Lat,Lng> - to snipe a pokemon at location Latitude, Longitude",
            "/snipetime <Lat,Lng> - return time that will be taken to snipe at given location",
            "/luckyegg - activate luckyegg",
            "/luckyeggcount - return number of luckyegg",
            "/ordincense - activate ordinary incense",
            "/ordincensecount - return number of ordinary incense",
            "/softbans - info about possible softbans"
        )
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text="\n".join(res))

    async def is_configured(self, update):
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                              text="No password nor master configured in TelegramTask section, bot will not accept any commands")

    async def is_master_numeric(self, update):
        outMessage = "Telegram message received from correct user, but master is not numeric, updating datastore."
        self.bot.logger.warn(outMessage)
        newconfig = self.config
        newconfig['master'] = update.message.chat_id
        self.grab_uid(update)
        self.bot.event_manager._handlers = [x for x in self.bot.event_manager._handlers if not isinstance(x, TelegramHandler)]
        self.bot.event_manager.add_handler(TelegramHandler(self.bot, newconfig))

    async def is_known_sender(self, update):
        outMessage = "Telegram message received from unknown sender. Please either make sure your username or ID is in TelegramTask/master, or a password is set in TelegramTask section and /login is issued"
        self.bot.logger.error(outMessage)
        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown', text="Please /login first")

    def tokenize(self, string, maxnum):
        spl = string.split(' ', maxnum - 1)
        while len(spl) < maxnum:
            spl.append(" ")
        return spl

    def evolve(self, chatid, uid):
        asyncio.run_coroutine_threadsafe(
            self.sendMessage(chat_id=chatid, parse_mode='HTML', text="Evolve logic not implemented yet"),
            asyncio.get_event_loop()
        )

    def upgrade(self, chatid, uid):
        asyncio.run_coroutine_threadsafe(
            self.sendMessage(chat_id=chatid, parse_mode='HTML', text="Upgrade logic not implemented yet"),
            asyncio.get_event_loop()
        )

    async def run(self):
        await asyncio.sleep(1)
        while True:
            if DEBUG_ON:
                self.bot.logger.info("Telegram loop running")
            if self._tbot is None:
                await self.connect()
            try:
                updates = await self._tbot.get_updates(offset=self.update_id, timeout=10)
                for update in updates:
                    self.update_id = update.update_id + 1
                    if update.message:
                        self.bot.logger.info(f"Telegram message from {update.message.from_user.username} "
                                            f"({update.message.from_user.id}): {update.message.text}")
                        if re.match(r'^/login [^ ]+', update.message.text):
                            self.authenticate(update)
                            continue
                        if self.config.get('password', None) is None and not self.config.get('master', None):
                            await self.is_configured(update)
                            continue
                        if not self.isAuthenticated(update.message.from_user.id) and self.master and \
                           not str(self.master).isnumeric() and str(self.master) == str(update.message.from_user.username):
                            await self.is_master_numeric(update)
                            continue
                        if not self.isAuthenticated(update.message.from_user.id):
                            await self.is_known_sender(update)
                            continue
                        self.grab_uid(update)
                        if update.message.text in ("/start", "/help"):
                            await self.send_start(update)
                            continue
                        if update.message.text == "/info":
                            await self.send_info(update)
                            continue
                        if update.message.text == "/logout":
                            await self.send_logout(update)
                            continue
                        if re.match("^/events", update.message.text):
                            await self.send_events(update)
                            continue
                        if re.match(r'^/sub ', update.message.text):
                            await self.send_subscription_updated(update)
                            continue
                        if re.match(r'^/unsub ', update.message.text):
                            await self.send_subscription_updated(update)
                            continue
                        if re.match(r'^/showsubs', update.message.text):
                            await self.showsubs(update)
                            continue
                        if re.match(r'^/top ', update.message.text):
                            cmd, num, order = self.tokenize(update.message.text, 3)
                            await self.send_top(update, num, order)
                            continue
                        if re.match(r'^/caught ', update.message.text):
                            cmd, num, order = self.tokenize(update.message.text, 3)
                            await self.send_caught(update, num, order)
                            continue
                        if re.match(r'^/evolved ', update.message.text):
                            cmd, num, order = self.tokenize(update.message.text, 3)
                            await self.send_evolved(update, num, order)
                            continue
                        if re.match(r'^/pokestops ', update.message.text):
                            cmd, num = self.tokenize(update.message.text, 2)
                            await self.send_pokestops(update, num)
                            continue
                        if re.match(r'^/hatched ', update.message.text):
                            cmd, num, order = self.tokenize(update.message.text, 3)
                            await self.send_hatched(update, num, order)
                            continue
                        if re.match(r'^/released ', update.message.text):
                            cmd, num, order = self.tokenize(update.message.text, 3)
                            await self.send_released(update, num, order)
                            continue
                        if re.match(r'^/vanished ', update.message.text):
                            cmd, num, order = self.tokenize(update.message.text, 3)
                            await self.send_vanished(update, num, order)
                            continue
                        if re.match(r'^/snipe ', update.message.text):
                            try:
                                cmd, pkm, location = self.tokenize(update.message.text, 3)
                                await self.request_snipe(update, pkm, location)
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/snipetime ', update.message.text):
                            try:
                                cmd, location = self.tokenize(update.message.text, 2)
                                await self.request_snipe_time(update, location)
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/luckyeggcount', update.message.text):
                            try:
                                await self.request_luckyegg_count(update)
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/luckyegg', update.message.text):
                            try:
                                if await self.request_luckyegg(update):
                                    self.bot.logger.info("Telegram has called for lucky egg. Success.")
                                else:
                                    self.bot.logger.info("Telegram has called for lucky egg. Failed.")
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/ordincensecount', update.message.text):
                            try:
                                await self.request_ordincense_count(update)
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/ordincense', update.message.text):
                            try:
                                if await self.request_ordincense(update):
                                    self.bot.logger.info("Telegram has called for ordinary incense. Success.")
                                else:
                                    self.bot.logger.info("Telegram has called for ordinary incense. Failed.")
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/itime', update.message.text):
                            try:
                                if await self.request_incensetime(update):
                                    self.bot.logger.info("Telegram has called for incense time. Success.")
                                else:
                                    self.bot.logger.info("Telegram has called for incense time. Failed.")
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/snipedisabled ', update.message.text):
                            try:
                                cmd, config = self.tokenize(update.message.text, 2)
                                await self.request_snipe_disable(update, config)
                            except:
                                await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                                       text="An Error has occurred")
                            continue
                        if re.match(r'^/softbans ', update.message.text):
                            cmd, num = self.tokenize(update.message.text, 2)
                            await self.send_softbans(update, num)
                            continue
                        await self.sendMessage(chat_id=update.message.chat_id, parse_mode='Markdown',
                                               text=f"Unrecognized command: {update.message.text}")
            except Exception as e:
                self.bot.logger.error(f"Telegram update processing failed: {e}")

class TelegramDBInit:
    def __init__(self, conn):
        self.conn = conn
        self.initDBstructure()

    def initDBstructure(self):
        db_structure = {
            "telegram_uids": "CREATE TABLE telegram_uids(uid TEXT CONSTRAINT upk PRIMARY KEY, username TEXT NOT NULL)",
            "tuids_username": "CREATE INDEX tuids_username ON telegram_uids(username)",
            "telegram_logins": "CREATE TABLE telegram_logins(uid TEXT CONSTRAINT tlupk PRIMARY KEY, logindate INTEGER DEFAULT (strftime('%s', 'now')))",
            "telegram_subscriptions": "CREATE TABLE telegram_subscriptions(uid TEXT, event_type TEXT, parameters TEXT, CONSTRAINT tspk PRIMARY KEY(uid, event_type, parameters))",
            "ts_uid": "CREATE INDEX ts_uid ON telegram_subscriptions(uid)"
        }
        for objname, sql in db_structure.items():
            self.initDBobject(objname, sql)

    def initDBobject(self, name, sql):
        res = self.conn.execute("SELECT sql, type FROM sqlite_master WHERE name = ?", (name,)).fetchone()
        if res and res[0] != sql:
            self.conn.execute(f"DROP {res[1]} {name}")
        if not res or res[0] != sql:
            self.conn.execute(sql)

class TelegramHandler(EventHandler):
    def __init__(self, bot, config):
        initiator = TelegramDBInit(bot.database)
        self.bot = bot
        self.tbot = None
        self.pokemons = config.get('alert_catch', {})
        self.whoami = "TelegramHandler"
        self.config = config
        self.chat_handler = ChatHandler(self.bot, self.pokemons)
        self._connect()

    def _connect(self):
        if self.tbot is None:
            self.bot.logger.info("Telegram bot not running. Starting")
            self.tbot = TelegramClass(self.bot, self.pokemons, self.config)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_in_executor(None, lambda: loop.run_until_complete(self.tbot.run()))

    def catch_notify(self, pokemon, cp, iv, params):
        if params == " ":
            return True
        try:
            oper = re.search(r'operator:([^ ]+)', params).group(1)
            rule_cp = int(re.search(r'cp:([0-9]+)', params).group(1))
            rule_iv = float(re.search(r'iv:([0-9.]+)', params).group(1))
            rule_pkmn = re.search(r'pokemon:([^ ]+)', params).group(1)
            return rule_pkmn == pokemon and (
                oper == "or" and (cp >= rule_cp or iv >= rule_iv) or cp >= rule_cp and iv >= rule_iv)
        except:
            return False

    async def handle_event(self, event, sender, level, formatted_msg, data):
        msg = None
        with self.bot.database as conn:
            subs = conn.execute(
                "SELECT uid, parameters, event_type FROM telegram_subscriptions WHERE event_type IN (?, 'all', 'debug')",
                (event,)
            ).fetchall()
            for sub in subs:
                if DEBUG_ON:
                    self.bot.logger.info(f"Processing sub {sub}")
                uid, params, event_type = sub
                if not self.tbot.isAuthenticated(uid):
                    continue
                if event != 'pokemon_caught' or self.catch_notify(data["pokemon"], int(data["cp"]), float(data["iv"]), params):
                    if DEBUG_ON:
                        self.bot.logger.info(f"Matched sub {sub} event {event}")
                    elif event_type == "debug":
                        self.bot.logger.info(f"[{event}] {msg}")
                    else:
                        msg = self.chat_handler.get_event(event, formatted_msg, data)
                    if msg is None:
                        continue
                else:
                    if DEBUG_ON:
                        self.bot.logger.info(f"No match sub {sub} event {event}")
        if msg is not None:
            if self.tbot is None:
                if DEBUG_ON:
                    self.bot.logger.info("handle_event Telegram bot not running.")
                try:
                    self._connect()
                except Exception as inst:
                    self.bot.logger.error(f"Unable to start Telegram bot; exception: {inst}")
                    self.tbot = None
                    return
            if self.tbot is not None:
                await self.tbot.sendMessage(chat_id=uid, parse_mode='Markdown', text=msg)