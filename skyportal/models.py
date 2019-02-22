import os.path
import re
import requests
import numpy as np

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql
from sqlalchemy.orm import backref, relationship, mapper

from baselayer.app.models import (init_db, join_model, Base, DBSession, ACL,
                                  Role, User, Token)

from . import schema


def is_owned_by(self, user_or_token):
    """Generic ownership logic for any `skyportal` ORM model.

    Models with complicated ownership logic should implement their own method
    instead of adding too many additional conditions here.
    """
    if hasattr(self, 'tokens'):
        return (user_or_token in self.tokens)
    elif hasattr(self, 'groups'):
        return bool(set(self.groups) & set(user_or_token.groups))
    elif hasattr(self, 'users'):
        return (user_or_token in self.users)
    else:
        raise NotImplementedError(f"{type(self).__name__} object has no owner")
Base.is_owned_by = is_owned_by


class NumpyArray(sa.types.TypeDecorator):
    impl = psql.ARRAY(sa.Float)

    def process_result_value(self, value, dialect):
        return np.array(value)


class Group(Base):
    name = sa.Column(sa.String, unique=True, nullable=False)

    sources = relationship('Source', secondary='group_sources', cascade='all')
    streams = relationship('Stream', secondary='stream_groups', cascade='all',
                           back_populates='groups')
    group_users = relationship('GroupUser', back_populates='group',
                               cascade='all', passive_deletes=True)
    users = relationship('User', secondary='group_users', cascade='all',
                         back_populates='groups')
    group_tokens = relationship('GroupToken', back_populates='group',
                               cascade='all', passive_deletes=True)
    tokens = relationship('Token', secondary='group_tokens', cascade='all',
                          back_populates='groups')


GroupToken = join_model('group_tokens', Group, Token)
Token.groups = relationship('Group', secondary='group_tokens', cascade='all',
                            back_populates='tokens')
Token.group_tokens = relationship('GroupToken', back_populates='token', cascade='all')

GroupUser = join_model('group_users', Group, User)
GroupUser.admin = sa.Column(sa.Boolean, nullable=False, default=False)


class Stream(Base):
    name = sa.Column(sa.String, unique=True, nullable=False)
    url = sa.Column(sa.String, unique=True, nullable=False)
    username = sa.Column(sa.String)
    password = sa.Column(sa.String)

    groups = relationship('Group', secondary='stream_groups', cascade='all',
                          back_populates='streams')


StreamGroup = join_model('stream_groups', Stream, Group)


User.group_users = relationship('GroupUser', back_populates='user', cascade='all')
User.groups = relationship('Group', secondary='group_users', cascade='all',
                           back_populates='users')


class Source(Base):
    id = sa.Column(sa.String, primary_key=True)
    # TODO should this column type be decimal? fixed-precison numeric
    ra = sa.Column(sa.Float)
    dec = sa.Column(sa.Float)
    red_shift = sa.Column(sa.Float, nullable=True)

    groups = relationship('Group', secondary='group_sources', cascade='all')
    comments = relationship('Comment', back_populates='source', cascade='all',
                            order_by="Comment.created_at")
    photometry = relationship('Photometry', back_populates='source',
                              cascade='all',
                              order_by="Photometry.observed_at")
    spectra = relationship('Spectrum', back_populates='source', cascade='all',
                           order_by="Spectrum.observed_at")
    thumbnails = relationship('Thumbnail', back_populates='source',
                              secondary='photometry', cascade='all')

    def add_linked_thumbnails(self):
        sdss_thumb = Thumbnail(photometry=self.photometry[0],
                               public_url=self.get_sdss_url(),
                               type='sdss')
        ps1_thumb = Thumbnail(photometry=self.photometry[0],
                              public_url=self.get_panstarrs_url(),
                              type='ps1')
        DBSession().add_all([sdss_thumb, ps1_thumb])
        DBSession().commit()

    def get_sdss_url(self):
        """Construct URL for public Sloan Digital Sky Survey (SDSS) cutout."""
        return (f"http://skyservice.pha.jhu.edu/DR9/ImgCutout/getjpeg.aspx"
                f"?ra={self.ra}&dec={self.dec}&scale=0.5&width=200&height=200"
                f"&opt=G&query=&Grid=on")

    def get_panstarrs_url(self):
        """Construct URL for public PanSTARRS-1 (PS1) cutout.

        The cutout service doesn't allow directly querying for an image; the
        best we can do is request a page that contains a link to the image we
        want (in this case a combination of the green/blue/red filters).
        """
        try:
            ps_query_url = (f"http://ps1images.stsci.edu/cgi-bin/ps1cutouts"
                            f"?pos={self.ra}+{self.dec}&filter=color&filter=g"
                            f"&filter=r&filter=i&filetypes=stack&size=400")
            response = requests.get(ps_query_url)
            match = re.search('src="//ps1images.stsci.edu.*?"', response.content.decode())
            return match.group().replace('src="', 'http:').replace('"', '')
        except (ValueError, ConnectionError) as e:
            return None


GroupSource = join_model('group_sources', Group, Source)
"""User.sources defines the logic for whether a user has access to a source;
   if this gets more complicated it should become a function/`hybrid_property`
   rather than a `relationship`.
"""
User.sources = relationship('Source', backref='users',
                            secondary='join(Group, group_sources).join(group_users)',
                            primaryjoin='group_users.c.user_id == users.c.id')


class Telescope(Base):
    name = sa.Column(sa.String, nullable=False)
    nickname = sa.Column(sa.String, nullable=False)
    lat = sa.Column(sa.Float, nullable=False)
    lon = sa.Column(sa.Float, nullable=False)
    elevation = sa.Column(sa.Float, nullable=False)
    diameter = sa.Column(sa.Float, nullable=False)

    instruments = relationship('Instrument', back_populates='telescope',
                               cascade='all')


class Instrument(Base):
    name = sa.Column(sa.String, nullable=False)
    type = sa.Column(sa.String, nullable=False)
    band = sa.Column(sa.String, nullable=False)

    telescope_id = sa.Column(sa.ForeignKey('telescopes.id',
                                           ondelete='CASCADE'),
                             nullable=False, index=True)
    telescope = relationship('Telescope', back_populates='instruments',
                             cascade='all')
    photometry = relationship('Photometry', back_populates='instrument',
                              cascade='all')
    spectra = relationship('Spectrum', back_populates='instrument',
                           cascade='all')


class Comment(Base):
    text = sa.Column(sa.String, nullable=False)
    attachment_name = sa.Column(sa.String, nullable=True)
    attachment_type = sa.Column(sa.String, nullable=True)
    attachment_bytes = sa.Column(sa.types.LargeBinary, nullable=True)

    user_id = sa.Column(sa.ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    user = relationship('User', back_populates='comments', cascade='all')
    source_id = sa.Column(sa.ForeignKey('sources.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    source = relationship('Source', back_populates='comments', cascade='all')


User.comments = relationship('Comment', back_populates='user', cascade='all',
                             order_by="Comment.created_at")


class Photometry(Base):
    __tablename__ = 'photometry'
    observed_at = sa.Column(sa.DateTime)
    time_format = sa.Column(sa.String, default='iso')
    time_scale = sa.Column(sa.String, default='tcb')
    mag = sa.Column(sa.Float)
    e_mag = sa.Column(sa.Float)
    lim_mag = sa.Column(sa.Float)
    filter = sa.Column(sa.String)  # TODO Enum?

    source_id = sa.Column(sa.ForeignKey('sources.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    source = relationship('Source', back_populates='photometry', cascade='all')
    instrument_id = sa.Column(sa.ForeignKey('instruments.id',
                                            ondelete='CASCADE'),
                              nullable=False, index=True)
    instrument = relationship('Instrument', back_populates='photometry',
                              cascade='all')
    thumbnails = relationship('Thumbnail', cascade='all')


class Spectrum(Base):
    __tablename__ = 'spectra'
    # TODO better numpy integration
    wavelengths = sa.Column(NumpyArray, nullable=False)
    fluxes = sa.Column(NumpyArray, nullable=False)
    errors = sa.Column(NumpyArray)

    source_id = sa.Column(sa.ForeignKey('sources.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    source = relationship('Source', back_populates='spectra', cascade='all')
    observed_at = sa.Column(sa.DateTime, nullable=False)
    # TODO program?
    instrument_id = sa.Column(sa.ForeignKey('instruments.id',
                                            ondelete='CASCADE'),
                              nullable=False, index=True)
    instrument = relationship('Instrument', back_populates='spectra',
                              cascade='all')

    @classmethod
    def from_ascii(cls, filename, source_id, instrument_id, observed_at):
        data = np.loadtxt(filename)
        if data.shape[1] != 2:  # TODO support other formats
            raise ValueError(f"Expected 2 columns, got {data.shape[1]}")

        return cls(wavelengths=data[:, 0], fluxes=data[:, 1],
                   source_id=source_id, instrument_id=instrument_id,
                   observed_at=observed_at)


#def format_public_url(context):
#    """TODO migrate this to broker tools"""
#    file_uri = context.current_parameters.get('file_uri')
#    if file_uri is None:
#        return None
#    elif file_uri.startswith('s3'):  # TODO is this reliable?
#        raise NotImplementedError
#    elif file_uri.startswith('http://'): # TODO is this reliable?
#        return file_uri
#    else:  # local file
#        return '/' + file_uri.lstrip('./')


class Thumbnail(Base):
    # TODO delete file after deleting row
    type = sa.Column(sa.Enum('new', 'ref', 'sub', 'sdss', 'ps1',
                             name='thumbnail_types', validate_strings=True))
    file_uri = sa.Column(sa.String(), nullable=True, index=False, unique=False)
    public_url = sa.Column(sa.String(), nullable=True, index=False, unique=False)

    photometry_id = sa.Column(sa.ForeignKey('photometry.id', ondelete='CASCADE'),
                              nullable=False, index=True)
    photometry = relationship('Photometry', back_populates='thumbnails', cascade='all')
    source = relationship('Source', back_populates='thumbnails', uselist=False,
                          secondary='photometry', cascade='all')


schema.setup_schema()
