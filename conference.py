#!/usr/bin/env python

__author__ = 'Yu Lei'


from datetime import datetime
import json
import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.ext import ndb

from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import ProfileForms
from utils import getUserId
from settings import WEB_CLIENT_ID
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import BooleanMessage
from models import ConflictException
from google.appengine.api import memcache
from models import StringMessage
from google.appengine.api import taskqueue

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKER"

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    typeOfSession=messages.StringField(1),
    websafeConferenceKey=messages.StringField(2),
)

SESSION_GET_BY_SPEAKER_REQUEST  = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker =messages.StringField(1),
    
)


SEESION_REQUEST  = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api( name='conference',
                version='v1',
                allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
                scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
            prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

# - - - Conference objects - - - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )

        return request


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

         # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "")
            for conf in conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
        path='getConferencesCreated',
        http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # make profile key
        p_key = ndb.Key(Profile, getUserId(user))
        # create ancestor query for this user
        conferences = Conference.query(ancestor=p_key)
        # get the user profile and display name
        prof = p_key.get()
        displayName = getattr(prof, 'displayName')
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, displayName) for conf in conferences]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
        path='filterPlayground',
        http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        q = Conference.query()
        # simple filter usage:
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

    @ndb.transactional(xg = True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:                                                                                                                                                               raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # TODO 1
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)

# ----------------------Session-----------------------------------------

    def _createSessionObject(self, request):
        """Create or update Conference object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        #get cinference key
        wsck = request.websafeConferenceKey
        # get conference object
        c_key = ndb.Key(urlsafe=wsck)
        conf = c_key.get()
        # check that conference exists or not
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)
        # check that user is owner
        if conf.organizerUserId != getUserId(endpoints.get_current_user()):
            raise endpoints.ForbiddenException(
                'You must be the organizer to create a session.')

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        # convert date and time from strings to Date objects; 
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:10],  "%H, %M").time()
        # allocate new Session ID with Conference key as parent
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        # make Session key from ID
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key
        data['websafeConferenceKey'] = wsck
        del data['sessionSafeKey']

        #  save session into database
        Session(**data).put()
        # This task wil send a confirmation email to the owner 
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_session_email'
        )
        return request

    @endpoints.method(SessionForm, SessionForm,
            path='createSession',
            http_method='POST', name='createSession')
    def createSession(self, request):
        """Create a session in a given conference; open only to the organizer of this conference."""
        return self._createSessionObject(request)

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        ss = SessionForm()
        for field in ss.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('date') or field.name.endswith('startTime'):
                    setattr(ss, field.name, str(getattr(session, field.name)))
                else:
                    setattr(ss, field.name, getattr(session, field.name))
            elif field.name == "sessionSafeKey":
                setattr(ss, field.name, session.key.urlsafe())
        ss.check_initialized()
        return ss

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Given a conference, returns all sessions."""
        # get the conference key
        wsck = request.websafeConferenceKey
        # fetch the conference with the target key
        conf = ndb.Key(urlsafe = wsck).get()
        # check whether the conference exists or not
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)
         # create ancestor query for all key matches for this conference
        sessions = Session.query()
        Sessions = sessions.filter(Session.websafeConferenceKey == wsck)
        # return set of SessionForm objects per conference
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions/{typeOfSession}',
            http_method='GET', name='getConferenceSessionsByType') 
    def getConferenceSessionsByType(self, request):
        """Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)."""
        # get the conference key
        wsck = request.websafeConferenceKey
        # get the type pf session we want
        typeOfSession = request.typeOfSession
        # fetch the conference with the target key
        conf = ndb.Key(urlsafe = wsck).get()
        # check whether the conference exists or not
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)
        # create ancestor query for all key matches for this conference and type is what we want
        sessions = Session.query()
        sessions = sessions.filter(Session.typeOfSession == typeOfSession, Session.websafeConferenceKey == wsck)
        # return set of SessionForm objects per Session
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    @endpoints.method(SESSION_GET_BY_SPEAKER_REQUEST, SessionForms,
            path='/sessions/{speaker}',
            http_method='GET', name='getSessionsBySpeaker') 
    def getSessionsBySpeaker(self, request):
        """Given a speaker, return all sessions given by this particular speaker, across all conferences."""
        sessions = Session.query()
        sessions = sessions.filter(Session.speaker == request.speaker)
        # return set of SessionForm objects
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])   

    @endpoints.method(CONF_GET_REQUEST, ProfileForms,
            path='/getAttenderByConference/{websafeConferenceKey}',
            http_method='GET', name='getAttenderByConference') 
    def getAttenderByConference(self, request):
        """Given a Conference, return all attenders join this conferences."""
        wsck = request.websafeConferenceKey
        profiles = Profile.query()
        attenders = []
        for pro in profiles:
            if wsck in pro.conferenceKeysToAttend:
                attenders.append(pro)
        # return set of SessionForm objects
        return ProfileForms(items=[self._copyProfileToForm(attender) for attender in attenders])    

    @endpoints.method(SEESION_REQUEST, ProfileForms,
            path='/getAttenderBySession/{sessionKey}',
            http_method='GET', name='getAttenderBySession') 
    def getAttenderBySession(self, request):
        """Given a Session, return all attenders join this session."""
        sessionKey = request.sessionKey
        profiles = Profile.query()
        attenders = []
        for pro in profiles:
            if sessionKey in pro.sessionKeysInWishlist:
                attenders.append(pro)
        # return set of ProfileForm objects
        return ProfileForms(items=[self._copyProfileToForm(attender) for attender in attenders])    

    @endpoints.method(SEESION_REQUEST, SessionForm,
            path="addSessionToWishlist",
            http_method="POST", name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add the session to the user's wishlist of sessions they are interested in attending"""
        #get session key
        sessionKey = request.sessionKey
        # get session object
        session = ndb.Key(urlsafe=sessionKey).get()
        # check that session exists or not
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % sessionKey)

        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        profile = self._getProfileFromUser()
        if not profile:
            raise endpoints.BadRequestException('Profile does not exist for user')
        # check if key and Session
        if not type(ndb.Key(urlsafe=sessionKey).get()) == Session:
            raise endpoints.NotFoundException('This key is not a Session instance')
        # add session to wishlist
        if sessionKey not in profile.sessionKeysInWishlist:
            try:
                profile.sessionKeysInWishlist.append(sessionKey)
                profile.put()
            except Exception:
                raise endpoints.InternalServerErrorException('Error in storing the wishlist')
        return self._copySessionToForm(session)

    @endpoints.method(message_types.VoidMessage,SessionForms, 
                      path='getSessionsInWishlist', http_method='GET',
                      name='getSessionsInWishlist')
    def getSessionsInWishlist(self,request):
        """Query for all the sessions in a conference that the user is interested in."""
        profile = self._getProfileFromUser()
        if not profile:
            raise endpoints.BadRequestException('Profile does not exist for user')
        # get all session keys
        sessionkeys = [ndb.Key(urlsafe=sessionkey) for sessionkey in profile.sessionKeysInWishlist]
        sessions = ndb.get_multi(sessionkeys)
        # return set of SessionForm objects per conference
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='speaker/get_features',
                      http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Get all featured speakers and return json data"""
        featuredSpeaker = memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY)
        if not featuredSpeaker:
            featuredSpeaker = ""
        # return json data
        return StringMessage(data=json.dumps(featuredSpeaker))


    @endpoints.method(message_types.VoidMessage,BooleanMessage, 
                      path='clearAllData', http_method='GET',
                      name='clearAllData')
    def clearAllData(self,request):
        """Clear all the data saved."""
        ndb.delete_multi(Session.query().fetch(keys_only = True))
        ndb.delete_multi(Conference.query().fetch(keys_only = True))
        profiles = Profile.query()
        for profile in profiles:
            profile.conferenceKeysToAttend = []
            profile.sessionKeysInWishlist = []
            profile.put()
        return  BooleanMessage(data=True)

    @staticmethod
    def _cacheFeaturedSpeaker():
        """Get Featured Speaker & assign to memcache;"""
        sessions = Session.query()
        speakersCounter = {}
        featured_speaker = ""
        num = 0
        for session in sessions:
            if session.speaker:
                if session.speaker not in speakersCounter:
                    speakersCounter[session.speaker] = 1
                else:
                    speakersCounter[session.speaker] += 1
                if speakersCounter[session.speaker] > num:
                    featured_speaker = session.speaker
                    num = speakersCounter[session.speaker] 
        memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, featured_speaker)
        return featured_speaker


# TODO

# registers API
api = endpoints.api_server([ConferenceApi]) 
