# Conference Organization APP using Google App Engine
This is the fourth project for "Full Stack Web Developer Nanodegree" on Udacity.

In this project, I developed the cloud-based APIs to support a provided conference organization application that exists on the web as well as can be put on Android and IOS application. Google Cloud Endpoints with Python is used to realize the API backend on Google APP Engine. 

The website is deployed on Google Cloud Platform: https://conference-central-app-1114.appspot.com

## Skills
- Python, HTML/CSS, Javascript, Google App Engine, Goolge Cloud Endpoints, Google Datastore, Google Memcache etc

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting
   your local server's address (by default [localhost:8080][5].)
1. Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool


## The Backend APIs
The APIs are:
![image](https://raw.githubusercontent.com/leiyudongyu/images/master/41.jpg)
![image](https://raw.githubusercontent.com/leiyudongyu/images/master/42.jpg)


## Add Sessions to a Conference
1. Session class 
	- Inherit `ndb.Model`.
	- Sessions are children of Conferences(In __init__py, I set session's key point to conference key, you can see the code of _createSessionObject() in __init__py)
 	- Has the following attributes:
 	
	```python
	class Session(ndb.Model):
		"""Session -- Session object"""
		name = ndb.StringProperty()  #Obvious is string
		highlights = ndb.StringProperty() #Obvious is string
		speaker = ndb.StringProperty(required=True)  #Obvious is string
		duration  = ndb.IntegerProperty()    #duration of a session is a number, so I set it to integer
		typeOfSession  = ndb.StringProperty(repeated=True) #Obvious is string
		date = ndb.DateProperty()   #It is a date, so I set to to date datatype
		startTime = ndb.TimeProperty() #It is a time in a day, so I set to to time datatype
		websafeConferenceKey =  ndb.StringProperty()  #Obvious is string
	```
        
2. SessionForm class
	- Inherit `messages.Message`.
	- Has the  attributes corresponding the ones in Session Model but sessionSafeKey is added for testing. 	
	```python
	class SessionForm(messages.Message):
		"""SessionForm -- Session outbound form message"""
		name  = messages.StringField(1)   
		highlights  = messages.StringField(2)
		speaker = messages.StringField(3)
		duration = messages.IntegerField(4)
		typeOfSession = messages.StringField(5, repeated=True)
		date  = messages.StringField(6) 
		startTime = messages.StringField(7) 
		sessionSafeKey  = messages.StringField(8)
		websafeConferenceKey  = messages.StringField(9)
	```
	
3. Speaker
	-  Defined as a string attribute in Session classes.
4. The following Endpoints methods are realized to manage sessions:
	- `getConferenceSessions(websafeConferenceKey)` -- Given a conference, return all sessions.
	- `getConferenceSessionsByType(websafeConferenceKey, typeOfSession)` -- Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)
	- `getSessionsBySpeaker(speaker)` -- Given a speaker, return all sessions given by this particular speaker, across all conferences
	- `createSession(SessionForm, websafeConferenceKey)` -- Open only to the organizer of the conference

## Add Sessions to User Wishlist
1. Profile class
	-  Added a new attribute `sessionKeysInWishlist = ndb.StringProperty(repeated=True)` into Profile class.
	-  In `sessionKeysInWishlist`, the `urlsafe` of the sessions which the user is interested in are stored.

2. The following Endpoints methods are realized to manage sessions:
	- `addSessionToWishlist(SessionKey)` -- adds the session to the user's list of sessions they are interested in attending.
	- `getSessionsInWishlist()` -- query for all the sessions in a conference that the user is interested in.

## Work on indexes and queries
1. Create indexes
2. Come up with 2 additional queries:
	-  `ProfileForms` is added for the following two methods.
	-  `getAttenderByConference(websafeConferenceKey)` -- Given a conference, return all attenders.
	-  `getAttenderBySession(sessionSafeKey)` -- Given a session, return all users who are interested in this session.
3. Solve the following query related problem

	Question: Let’s say that you don't like workshops and you don't like sessions after 7 pm. How would you handle a query for all non-workshop sessions before 7 pm? What is the problem for implementing this query? What ways to solve it did you think of?

	Answer: Because google datastore APIs only support one inequality filter for one property in a query, the question above need two property(typeOfSession, and startTime) we can not get the result in only one query. In this question two properties need to be filtered. But we can seperate the query into two by performing twice filterings. You can query the workshop first<br/>
```
p = Session.query()
p = p.filter(Session.typeOfSession != 'workshop')
p = p.order(Session.typeOfSession)
p = p.order(Session.date)
p = p.order(Session.startTime)
result = [session for session in p if session.startTime < time(19)]
```

## Add a Task
When a new session is added, A task is added to the default push queue for each speaker in the new session's speaker list. The task runs the `CheckFeaturedSpeakerHandler` (main.py) which updates the memcache key for a particular conference with a new speaker name (string) if the speaker already has other sessions in the datastore of the same conference.<br/>
1.  Adding a one-time task to check the featured speaker into `taskqueue` when the new session creating.<br/>
2. `getFeaturedSpeaker()` method is used to get the featured speaker.<br/>
This is detected during each call to the conference.createSession endpoint. 
