"""
Database models for StockPerformer authentication.
Tables: users, login_sessions
"""
import os, uuid
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text, DateTime, Boolean, ForeignKey, event
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
_DB_PATH     = os.path.join(BASE_DIR, 'stockperformer.db')
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{_DB_PATH}')

# Heroku Postgres uses "postgres://" but SQLAlchemy needs "postgresql://"
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

_is_sqlite = DATABASE_URL.startswith('sqlite')

engine = create_engine(
    DATABASE_URL,
    connect_args={'check_same_thread': False, 'timeout': 15} if _is_sqlite else {},
    pool_pre_ping=True,
)

# Enable WAL mode on SQLite — allows concurrent reads alongside writes
if _is_sqlite:
    @event.listens_for(engine, 'connect')
    def _set_wal(dbapi_conn, _rec):
        dbapi_conn.execute('PRAGMA journal_mode=WAL')
        dbapi_conn.execute('PRAGMA synchronous=NORMAL')


Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'

    id            = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = Column(String(254), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)   # NULL for OAuth-only accounts
    display_name  = Column(String(120), nullable=True)
    avatar_url    = Column(Text,        nullable=True)

    # One column per provider keeps lookups simple
    google_id    = Column(String(128), unique=True, nullable=True, index=True)
    facebook_id  = Column(String(128), unique=True, nullable=True, index=True)
    microsoft_id = Column(String(128), unique=True, nullable=True, index=True)
    apple_id     = Column(String(128), unique=True, nullable=True, index=True)

    is_active  = Column(Boolean,  default=True,           nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)

    sessions = relationship(
        'LoginSession', back_populates='user',
        cascade='all, delete-orphan',
        order_by='LoginSession.created_at.desc()',
    )

    def to_dict(self):
        return {
            'id':           self.id,
            'email':        self.email,
            'display_name': self.display_name,
            'avatar_url':   self.avatar_url,
            'created_at':   self.created_at.isoformat() if self.created_at else None,
        }


class LoginSession(Base):
    __tablename__ = 'login_sessions'

    id            = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id       = Column(String(36),  ForeignKey('users.id'), nullable=False, index=True)

    ip_address    = Column(String(45),  nullable=True)   # supports IPv6
    user_agent    = Column(Text,        nullable=True)
    country       = Column(String(80),  nullable=True)
    city          = Column(String(120), nullable=True)
    auth_provider = Column(String(20),  nullable=False, default='email')

    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at   = Column(DateTime, nullable=True)
    is_active    = Column(Boolean,  default=True, nullable=False)

    user = relationship('User', back_populates='sessions')

    def to_dict(self, current_sid=None):
        return {
            'id':            self.id,
            'ip_address':    self.ip_address,
            'country':       self.country,
            'city':          self.city,
            'user_agent':    self.user_agent,
            'auth_provider': self.auth_provider,
            'created_at':    self.created_at.isoformat()   if self.created_at   else None,
            'last_seen_at':  self.last_seen_at.isoformat() if self.last_seen_at else None,
            'is_active':     self.is_active,
            'is_current':    self.id == current_sid,
        }


def init_db():
    """Create all tables. Safe to call multiple times."""
    Base.metadata.create_all(engine)
