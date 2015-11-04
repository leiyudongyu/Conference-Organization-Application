#!/usr/bin/env python
import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from conference import ConferenceApi
from google.appengine.api import app_identity
from google.appengine.api import mail
from google.appengine.api import memcache

class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        # TODO 1
        # use _cacheAnnouncement() to set announcement in Memcache
        ConferenceApi._cacheAnnouncement()

class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )
class SendConfirmationOfSessionEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Session!',            # subj
            'Hi, you have created a new Session in the following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )

class CheckFeaturedSpeakerHandler(webapp2.RequestHandler):
    def post(self):
        wsck = self.request.get('websafeConferenceKey')
        speaker = self.request.get('speaker')
        # Set new featured speaker in memcache if necessary
        sessions = ConferenceApi._cacheFeaturedSpeaker(wsck, speaker)
        if sessions.count() >= 2:
            memcache.set(key="featuredSpeaker_" + wsck, value=speaker)

app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/send_confirmation_session_email', SendConfirmationOfSessionEmailHandler),
    ('/tasks/check_featured_speaker', CheckFeaturedSpeakerHandler)
], debug=True)
