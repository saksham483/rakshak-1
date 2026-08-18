from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from . import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    from . import models
    models.Base.metadata.create_all(bind=engine)
