import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 5})
Session = sessionmaker(engine, expire_on_commit=False)


# tests point the stand at a scratch database without reimporting every module
def bind(new_engine) -> None:
    global engine
    engine = new_engine
    Session.configure(bind=new_engine)
