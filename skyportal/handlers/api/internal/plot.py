from baselayer.app.access import auth_or_token
from ...base import BaseHandler
from .... import plot
from ....models import ClassicalAssignment, Source

import numpy as np
from astropy import time as ap_time
import pandas as pd


# TODO this should distinguish between "no data to plot" and "plot failed"
class PlotPhotometryHandler(BaseHandler):
    @auth_or_token
    def get(self, obj_id):
        height = self.get_query_argument("plotHeight", 300)
        width = self.get_query_argument("plotWidth", 600)
        json = plot.photometry_plot(
            obj_id, self.current_user, height=int(height), width=int(width),
        )
        self.success(data={'bokehJSON': json, 'url': self.request.uri})


class PlotSpectroscopyHandler(BaseHandler):
    @auth_or_token
    def get(self, obj_id):
        spec_id = self.get_query_argument("spectrumID", None)
        json = plot.spectroscopy_plot(obj_id, spec_id)
        self.success(data={'bokehJSON': json, 'url': self.request.uri})


class PlotAirmassHandler(BaseHandler):
    @auth_or_token
    def get(self, assignment_id):
        assignment = ClassicalAssignment.query.get(assignment_id)
        if assignment is None:
            return self.error('Invalid assignment id.')
        obj = assignment.obj
        permission_check = Source.get_obj_if_owned_by(obj.id, self.current_user)
        if permission_check is None:
            return self.error('Invalid assignment id.')

        sunset = assignment.run.sunset
        sunrise = assignment.run.sunrise

        time = np.linspace(sunset.unix, sunrise.unix, 50)
        time = ap_time.Time(time, format='unix')

        airmass = obj.airmass(assignment.run.instrument.telescope, time)
        time = time.isot
        df = pd.DataFrame({'time': time, 'airmass': airmass})
        json = df.to_dict(orient='records')
        return self.success(data=json)
