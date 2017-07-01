import requests
import re
import logging
import aiohttp
import asyncio
import async_timeout
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

class AdtPulsedotcom(object):
    """
    Access to adtpulse.com partners and accounts.

    This class is used to interface with the options available through
    portal.adtpulse.com. The basic functions of checking system status and arming
    and disarming the system are possible.
    """
    
    # AdtPulse.com constants
    
    # AdtPulse.com baseURL
    ADTPULSEDOTCOM_URL = 'https://portal.adtpulse.com'
    
    # AdtPulse.com contextPath
    def adtpulse_version (ADTPULSEDOTCOM_URL):
        """Determine current ADT Pulse version"""
        resp = requests.get(ADTPULSEDOTCOM_URL)
        parsed = BeautifulSoup(resp.content, 'html.parser')
        adtpulse_script = parsed.find_all('script', type='text/javascript')[4].string
        if "=" in adtpulse_script:
            param, value = adtpulse_script.split("=",1)
        adtpulse_version = value
        adtpulse_version = adtpulse_version[1:-2]
        return(adtpulse_version)
    
    ADTPULSEDOTCOM_CONTEXT_PATH = adtpulse_version(ADTPULSEDOTCOM_URL)
    
    # Page elements on portal.adtpulse.com that are needed
    # Using a dict for the attributes to set whether it is a name or id for locating the field
    LOGIN_URL = ADTPULSEDOTCOM_URL + ADTPULSEDOTCOM_CONTEXT_PATH + '/access/signin.jsp'
    LOGIN_USERNAME = ('name', 'usernameForm')
    LOGIN_PASSWORD = ('name', 'passwordForm')
    LOGIN_BUTTON = ('name', 'signin')
    
    DASHBOARD_URL = ADTPULSEDOTCOM_URL + ADTPULSEDOTCOM_CONTEXT_PATH + '/summary/summary.jsp'
    
    STATUS_IMG = ('id', 'divOrb')
    
    BTN_DISARM = ('id', 'security_button_1', 'Disarmed')
    BTN_ARM_STAY = ('id', 'security_button_3', 'Arm Stay')
    BTN_ARM_AWAY = ('id', 'security_button_2', 'Arm Away')
    
    # Image to check if hidden or not while the system performs it's action.
    STATUS_UPDATING = {'id': 'divOrb'}    
    # Session key regex to extract the current session
    SESSION_KEY_RE = re.compile(
        '{url}(?P<JSESSIONID>.*)'.format(url=LOGIN_URL))
    
    # ADTPULSE.COM CSS MAPPINGS
    USERNAME = 'usernameForm'
    PASSWORD = 'passwordForm'
    
    LOGIN_CONST = 'signin'
    
    ERROR_CONTROL = 'divOrbWarningsContainer'
    MESSAGE_CONTROL = 'warnMsgContents'
    
    # Event validation
    EVENTVALIDATION = '__EVENTVALIDATION'
    DISARM_EVENT_VALIDATION = \
        'MnXvTutfO7KZZ1zZ7QR19E0sfvOVCpK7SV' \
        'yeJ0IkUkbXpfEqLa4fa9PzFK2ydqxNal'
    ARM_STAY_EVENT_VALIDATION = \
        '/CwyHTpKH4aUp/pqo5gRwFJmKGubsvmx3RI6n' \
        'IFcyrtacuqXSy5dMoqBPX3aV2ruxZBTUVxenQ' \
        '7luwjnNdcsxQW/p+YvHjN9ialbwACZfQsFt2o5'
    ARM_AWAY_EVENT_VALIDATION = '3ciB9sbTGyjfsnXn7J4LjfBvdGlkqiHoeh1vPjc5'
    
    DISARM_COMMAND = 'Disarm'
    ARM_STAY_COMMAND = 'Arm Stay'
    ARM_AWAY_COMMAND = 'Arm Away'
    
    ARMING_PANEL = '#ctl00_phBody_pnlArming'
    ALARM_STATE = 'divOrbTextSummary'

    COMMAND_LIST = {'Disarm': {'command': DISARM_COMMAND,
                           'eventvalidation': DISARM_EVENT_VALIDATION},
                'Arm+Stay': {'command': ARM_STAY_COMMAND,
                             'eventvalidation': ARM_STAY_EVENT_VALIDATION},
                'Arm+Away': {'command': ARM_AWAY_COMMAND,
                             'eventvalidation': ARM_AWAY_EVENT_VALIDATION}}
    
    def __init__(self, username, password, websession, loop):
        """
        Use aiohttp to make a request to alarm.com

        :param username: AdtPulse.com username
        :param password: AdtPulse.com password
        :param websession: AIOHttp Websession
        :param loop: Async loop.
        """
        self._username = username
        self._password = password
        self._websession = websession
        self._loop = loop
        self._login_info = None
        self.state = None

    @asyncio.coroutine
    def async_login(self):
        """Login to AdtPulse.com."""
        _LOGGER.debug('Attempting to log into AdtPulse.com...')

        # Get the session key for future logins.
        response = None
        try:
            with async_timeout.timeout(10, loop=self._loop):
                response = yield from self._websession.get(
                    self.LOGIN_URL)

            _LOGGER.debug(
                'Response status from AdtPulse.com: %s',
                response.status)
            text = yield from response.text()
            _LOGGER.debug(text)
            tree = BeautifulSoup(text, 'html.parser')
            self._login_info = {
                'sessionkey': response.cookies['JSESSIONID'].value
            }

            _LOGGER.debug(self._login_info)
            _LOGGER.info('Successfully retrieved sessionkey from AdtPulse.com')

        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOGGER.error('Can not get login page from AdtPulse.com')
            return False
        except AttributeError:
            _LOGGER.error('Unable to get sessionKey from AdtPulse.com')
            raise

        # Login params to pass during the post
        params = {
            self.USERNAME: self._username,
            self.PASSWORD: self._password
        }

        try:
            # Make an attempt to log in.
            with async_timeout.timeout(10, loop=self._loop):
                response = yield from self._websession.post(
                    self.LOGIN_URL.format, data=params)
            _LOGGER.debug(
                'Status from AdtPulse.com login %s', response.status)
            _LOGGER.info('Successful login to AdtPulse.com')        
        
        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOGGER.error("Can not load login page from AdtPulse.com")
            return False

    @asyncio.coroutine
    def async_update(self):
        """Fetch the latest state."""
        _LOGGER.debug('Calling update on AdtPulse.com')
        response = None
        if not self._login_info:
            yield from self.async_login()
        try:
            with async_timeout.timeout(10, loop=self._loop):
                response = yield from self._websession.get(
                    self.DASHBOARD_URL.format)

            _LOGGER.debug('Response from AdtPulse.com: %s', response.status)
            text = yield from response.text()
            _LOGGER.debug(text)
            tree = BeautifulSoup(text, 'html.parser')
            try:
                self.state = tree.select(self.ALARM_STATE)[0].get_text()
                _LOGGER.debug(
                    'Current alarm state: %s', self.state)
            except IndexError:
                # We may have timed out. Re-login again
                self.state = None
                self._login_info = None
                yield from self.async_update()
        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOGGER.error("Can not load login page from AdtPulse.com")
            return False
        finally:
            if response is not None:
                yield from response.release()

    @asyncio.coroutine
    def _send(self, event):
        """Generic function for sending commands to AdtPulse.com

        :param event: Event command to send to alarm.com
        """
        _LOGGER.debug('Sending %s to AdtPulse.com', event)

        try:
            with async_timeout.timeout(10, loop=self._loop):
                response = yield from self._websession.post(
                    self.DASHBOARD_URL.format(
                        self._login_info['sessionkey']),
                    data={
                        self.EVENTVALIDATION:
                            self.COMMAND_LIST[event]['eventvalidation'],
                        self.COMMAND_LIST[event]['command']: event})

                _LOGGER.debug(
                    'Response from AdtPulse.com %s', response.status)
                text = yield from response.text()
                tree = BeautifulSoup(text, 'html.parser')
                try:
                    message = tree.select(
                        '#{}'.format(self.MESSAGE_CONTROL))[0].get_text()
                    if 'command' in message:
                        _LOGGER.debug(message)
                        # Update adtpulse.com status after calling state change.
                        yield from self.async_update()
                except IndexError:
                    # May have been logged out
                    yield from self.async_login()
                    if event == 'Disarm':
                        yield from self.async_alarm_disarm()
                    elif event == 'Arm+Stay':
                        yield from self.async_alarm_arm_away()
                    elif event == 'Arm+Away':
                        yield from self.async_alarm_arm_away()

        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOGGER.error('Error while trying to disarm AdtPulse.com system')
        finally:
            if response is not None:
                yield from response.release()

    @asyncio.coroutine
    def async_alarm_disarm(self):
        """Send disarm command."""
        yield from self._send('Disarm')

    @asyncio.coroutine
    def async_alarm_arm_home(self):
        """Send arm hom command."""
        yield from self._send('Arm+Stay')

    @asyncio.coroutine
    def async_alarm_arm_away(self):
        """Send arm away command."""
        yield from self._send('Arm+Away')
