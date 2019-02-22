# This module acts as a placeholder for generated schema.  After
# `setup_schema` is run from `models`, each table will have an
# associated schema here.  E.g., `models.Dog` will be matched by `schema.Dog`.


# From
# https://marshmallow-sqlalchemy.readthedocs.io/en/latest/recipes.html#automatically-generating-schemas-for-sqlalchemy-models

from marshmallow_sqlalchemy import (
    ModelConversionError as _ModelConversionError,
    ModelSchema as _ModelSchema
)

from marshmallow import (Schema as _Schema, fields)
from marshmallow_enum import EnumField

import sqlalchemy as sa
from sqlalchemy.orm import mapper

from baselayer.app.models import (
    Base as _Base,
    DBSession as _DBSession
)

import sys
import inspect
from enum import Enum


class ApispecEnumField(EnumField):
    """See https://github.com/justanr/marshmallow_enum/issues/24#issue-335162592
    """
    def __init__(self, enum, *args, **kwargs):
        super().__init__(enum, *args, **kwargs)
        self.metadata['enum'] = [e.name for e in enum]


class Response(_Schema):
    status = ApispecEnumField(Enum('status', ['error', 'success']), required=True)
    message = fields.String()
    data = fields.Dict()


class Error(Response):
    status = ApispecEnumField(Enum('status', ['error']), required=True)


def success(schema_name, base_schema=None):
    schema_fields = {
        'status': ApispecEnumField(Enum('status', ['success']), required=True),
        'message': fields.String(),
    }

    if base_schema is not None:
        if isinstance(base_schema, list):
            schema_fields['data'] = fields.List(
                fields.Nested(base_schema[0]),
            )
        else:
            schema_fields['data'] = fields.Nested(base_schema)

    return type(schema_name, (_Schema,), schema_fields)


def setup_schema():
    """For each model, install a marshmallow schema generator as
    `model.__schema__()`, and add an entry to the `schema`
    module.

    """
    for class_ in _Base._decl_class_registry.values():
        if hasattr(class_, '__tablename__'):
            if class_.__name__.endswith('Schema'):
                raise _ModelConversionError(
                    "For safety, setup_schema can not be used when a"
                    "Model class ends with 'Schema'"
                )

            class Meta(object):
                model = class_
                sqla_session = _DBSession

            schema_class_name = '%s' % class_.__name__

            schema_class = type(
                schema_class_name,
                (_ModelSchema,),
                {'Meta': Meta}
            )

            setattr(class_, '__schema__', schema_class)
            setattr(sys.modules[__name__], class_.__name__,
                    schema_class())


def register_components(spec):
    print('Registering schemas with APISpec')

    schemas = inspect.getmembers(
        sys.modules[__name__],
        lambda m: isinstance(m, _Schema)
    )

    for (name, schema) in schemas:
        spec.components.schema(name, schema=schema)

        single = 'Single' + name
        arrayOf = 'ArrayOf' + name + 's'
        spec.components.schema(single, schema=success(single, schema))
        spec.components.schema(arrayOf, schema=success(arrayOf, [schema]))


# Replace schemas by instantiated versions
# These are picked up in `setup_schema` for the registry
Response = Response()
Error = Error()
Success = success('Success')
