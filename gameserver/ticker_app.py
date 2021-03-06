import logging.config
import os
from time import sleep, time

from google.appengine.ext import deferred
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from flask import Flask, Blueprint, request

from gameserver.database import db
from gameserver import settings
from gameserver.game import Game

from gameserver.controllers import _do_tick, _league_table

log = logging.getLogger(__name__)
db_session = db.session
game = Game()

TICKINTERVAL = 3

def configure_app(flask_app):
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI', settings.SQLALCHEMY_DATABASE_URI)
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = settings.SQLALCHEMY_TRACK_MODIFICATIONS
    flask_app.config['SWAGGER_UI_DOC_EXPANSION'] = settings.RESTPLUS_SWAGGER_UI_DOC_EXPANSION
    flask_app.config['RESTPLUS_VALIDATE'] = settings.RESTPLUS_VALIDATE
    flask_app.config['RESTPLUS_MASK_SWAGGER'] = settings.RESTPLUS_MASK_SWAGGER
    flask_app.config['ERROR_404_HELP'] = settings.RESTPLUS_ERROR_404_HELP
    flask_app.config['DEBUG'] = True
    flask_app.config['SQLALCHEMY_ECHO'] = False

def initialize_app(flask_app):
    configure_app(flask_app)
    db.app = flask_app
    db.init_app(flask_app)
    with flask_app.app_context():
        import models
        models.Base.metadata.create_all(bind=db.engine)

def create_app():
    app = Flask(__name__)
    initialize_app(app)
    return app

app = create_app()

@app.route('/_ah/start')
def scheduler():
    log.info('Ticker instance started')
    while True:
        if game.is_running(): 
            try:
                task = taskqueue.add(
                    url='/v1/game/tick',
                    queue_name='tickqueue',
                    method='PUT',
                    target='tickworker',
                    name="tick-{}".format(int(time()) // settings.TICKINTERVAL)
                    )
                log.info('Tick task added to queue')
            except (taskqueue.TaskAlreadyExistsError, taskqueue.TombstonedTaskError):
                pass
        else:
            log.info('Tick skipped as game stopped')
        db_session.rollback()
        sleep(settings.TICKINTERVAL)

def main(): # pragma: no cover
    app = create_app()
    log.info('>>>>> Starting development server at http://{}/api/ <<<<<'.format(app.config['SERVER_NAME']))
    app.run(debug=settings.FLASK_DEBUG)

if __name__ == "__main__": # pragma: no cover
    main()

