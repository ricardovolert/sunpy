# Author: Rishabh Sharma <rishabh.sharma.gunner@gmail.com>
# This module was developed under funding provided by
# Google Summer of Code 2014

from sunpy.util.datatype_factory_base import BasicRegistrationFactory
from sunpy.util.datatype_factory_base import NoMatchError
from sunpy.util.datatype_factory_base import MultipleMatchError

from sunpy.net.vso import VSOClient
from .. import attr

__all__ = ['Fido']


class UnifiedResponse(list):
    """
    The object used to store responses from the unified downloader.

    Properties
    ----------
    file_num : int
        The total number of files found as a result of the query.

    """
    def __init__(self, lst):

        tmplst = []
        for block in lst:
            block[0].client = block[1]
            tmplst.append(block[0])
        super(UnifiedResponse, self).__init__(tmplst)
        self._numfile = 0
        for qblock in self:
            self._numfile += len(qblock)

    @property
    def file_num(self):
        return self._numfile

    def _repr_html_(self):
        ret = ''
        for block in self:
            ret += block._repr_html_()

        return ret


class DownloadResponse(list):
    """
    Object returned by clients servicing the query.
    """

    def __init__(self, lst):
        super(DownloadResponse, self).__init__(lst)

    def wait(self, progress=True):
        """
        Waits for all files to download completely and then return.

        Parameters
        ----------
        progress : `bool`
            if true, display a progress bar.

        Returns
        -------
        List of file paths to which files have been downloaded.
        """
        filelist = []
        for resobj in self:
            filelist.extend(resobj.wait(progress=progress))

        return filelist


"""
Construct a simple AttrWalker to split up searches into blocks of attrs being
'anded' with AttrAnd.

This pipeline only understands AttrAnd and AttrOr, Fido.search passes in an
AttrAnd object of all the query parameters, if an AttrOr is encountered the
query is split into the component parts of the OR, which at somepoint will end
up being an AttrAnd object, at which point it is passed into
_get_registered_widget.
"""
query_walker = attr.AttrWalker()


@query_walker.add_creator(attr.AttrAnd)
def _create_and(walker, query, factory):
    qresponseobj, qclient = factory._get_registered_widget(*query.attrs)
    return [(qresponseobj, qclient)]


@query_walker.add_creator(attr.AttrOr)
def _create_or(walker, query, factory):
    qblocks = []
    for attrblock in query.attrs:
        qblocks.extend(walker.create(attr.and_(attrblock), factory))

    return qblocks


class UnifiedDownloaderFactory(BasicRegistrationFactory):
    def search(self, *query):
        """
        Query for data in form of multiple parameters.

        Examples
        --------
        Query for LYRALightCurve data for the time range ('2012/3/4','2012/3/6')

        >>> from sunpy.net.vso.attrs import Time, Instrument
        >>> unifresp = Fido.search(Time('2012/3/4', '2012/3/6'), Instrument('lyra'))

        Query for data from Nobeyama Radioheliograph and RHESSI

        >>> unifresp = Fido.search(Time('2012/3/4', '2012/3/6'), Instrument('norh') | Instrument('rhessi'))

        Query for 304 Angstrom SDO AIA data with a cadence of 10 minutes

        >>> import astropy.units as u
        >>> from sunpy.net.vso.attrs import Time, Instrument, Wavelength, Sample
        >>> unifresp = Fido.search(Time('2012/3/4', '2012/3/6'), Instrument('AIA'), Wavelength(304*u.angstrom, 304*u.angstrom), Sample(10*u.minute))

        Parameters
        ----------
        query : `sunpy.net.vso.attrs`, `sunpy.net.jsoc.attrs`
            A query consisting of multiple parameters which define the
            requested data.  The query is specified using attributes from the
            VSO and the JSOC.  The query can mix attributes from the VSO and
            the JSOC.

        Returns
        -------
        `sunpy.net.dataretriever.downloader_factory.UnifiedResponse` object
            Container of responses returned by clients servicing query.

        Notes
        -----
        The conjunction 'and' transforms query into disjunctive normal form
        ie. query is now of form A & B or ((A & B) | (C & D))
        This helps in modularising query into parts and handling each of the
        parts individually.
        """
        query = attr.and_(*query)
        return UnifiedResponse(query_walker.create(query, self))

    def fetch(self, query_result, wait=True, progress=True, **kwargs):
        """
        Downloads the files pointed at by URLs contained within UnifiedResponse
        object.

        Parameters
        ----------
        query_result : `sunpy.net.dataretriever.downloader_factory.UnifiedResponse`
            Container returned by query method.

        wait : `bool`
            fetch will wait until the download is complete before returning.

        progress : `bool`
            Show a progress bar while the download is running.

        Returns
        -------
        `sunpy.net.dataretriever.downloader_factory.DownloadResponse`

        Example
        --------
        >>> from sunpy.net.vso.attrs import Time, Instrument
        >>> unifresp = Fido.search(Time('2012/3/4','2012/3/6'), Instrument('AIA'))
        >>> downresp = Fido.get(unifresp)
        >>> file_paths = downresp.wait()
        """
        reslist = []
        for block in query_result:
            reslist.append(block.client.get(block, **kwargs))

        results = DownloadResponse(reslist)

        if wait:
            return results.wait(progress=progress)
        else:
            return results

    def __call__(self, *args, **kwargs):
        raise NotImplementedError

    def _check_registered_widgets(self, *args):
        """Factory helper function"""
        candidate_widget_types = list()
        for key in self.registry:

            if self.registry[key](*args):
                candidate_widget_types.append(key)

        n_matches = len(candidate_widget_types)
        if n_matches == 0:
            if self.default_widget_type is None:
                raise NoMatchError(
                    "No client understands this query, check your arguments to search.")
            else:
                return [self.default_widget_type]
        elif n_matches == 2:
            # If two clients have reported they understand this query, and one
            # of them is the VSOClient, then we ignore VSOClient.
            if VSOClient in candidate_widget_types:
                candidate_widget_types.remove(VSOClient)

        # Finally check that we only have one match.
        if len(candidate_widget_types) > 1:
            candidate_names = [cls.__name__ for cls in candidate_widget_types]
            raise MultipleMatchError(
                "Multiple clients understood this search,"
                " please provide a more specific query. {}".format(
                    candidate_names))

        return candidate_widget_types

    def _get_registered_widget(self, *args):
        """Factory helper function"""
        candidate_widget_types = self._check_registered_widgets(*args)
        tmpclient = candidate_widget_types[0]()
        return tmpclient.query(*args), tmpclient


Fido = UnifiedDownloaderFactory(
    additional_validation_functions=['_can_handle_query'])
