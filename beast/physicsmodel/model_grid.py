from __future__ import (absolute_import, division, print_function)
import os

import numpy as np

from astropy import units

from . import grid
from . import creategrid
from .stars import isochrone
from .stars.isochrone import ezIsoch
from .grid_and_prior_weights import compute_age_mass_metallicity_weights

__all__ = ['make_iso_table', 'make_spectral_grid', 'add_stellar_priors',
           'make_extinguished_sed_grid']

def make_iso_table(project, oiso=None, logtmin=6.0, logtmax=10.13, dlogt=0.05,
                   z=[0.0152]):
    """
    The isochrone tables are loaded (downloading if necessary)

    Parameters
    ----------
    project: str
        project name

    oiso: isochrone.Isochrone object
        contains the full isochrones information

    logtmin: float
        log-age min

    logtmax: float
        log-age max

    dlogt: float
        log-age step to request

    z: float or sequence
        list of metalicity values, where default (Z=0.152) is adopted Z_sun
        for PARSEC/COLIBRI models

    Returns
    -------
    fname: str
       name of saved file

    oiso: isochrone.Isochrone object
        contains the full isochrones information
    """
    iso_fname = '%s/%s_iso.csv' % (project, project)
    if not os.path.isfile(iso_fname):
        if oiso is None: 
            oiso = isochrone.PadovaWeb()
        
        t = oiso._get_t_isochrones(max(5.0, logtmin), min(10.13, logtmax),
                                   dlogt, z)
        t.header['NAME'] = '{0} Isochrones'.format('_'.join(iso_fname.split('_')[:-1]))
        print('{0} Isochrones'.format('_'.join(iso_fname.split('_')[:-1])))
    
        t.write(iso_fname)

    # read in the isochrone data from the file
    #   not sure why this is needed, but reproduces previous ezpipe method
    oiso = ezIsoch(iso_fname)
        
    return (iso_fname, oiso)

def make_spectral_grid(project, oiso, osl=None, bounds={}, distance=None,
                       verbose=True,
                       add_spectral_properties_kwargs=None, **kwargs):
    """
    The spectral grid is generated using the stellar parameters by
    interpolation of the isochrones and the generation of spectra into the
    physical units

    Parameters
    ----------
    project: str
        project name

    oiso: isochrone.Isochrone object
        set of isochrones to use

    osl: stellib.Stellib object
        Spectral library to use (default stellib.Kurucz)

    distance: float
        Distance at which models should be shifted
        0 means absolute magnitude.
        Expecting pc units

    add_spectral_properties_kwargs: dict
        keyword arguments to call :func:`add_spectral_properties`
        to add model properties from the spectra into the grid property table

    Returns
    -------
    fname: str
       name of saved file

    g: grid.SpectralGrid object
        spectral grid to transform
    """
    spec_fname = '%s/%s_spec_grid.hd5' % (project, project)

    if not os.path.isfile(spec_fname):
        osl = osl or stellib.Kurucz()

        #filter extrapolations of the grid with given sensitivities in logg
        #  and logT
        if 'dlogT' not in bounds:
            bounds['dlogT'] = 0.1
        if 'dlogg' not in bounds:
            bounds['dlogg'] = 0.3

        #make the spectral grid
        if verbose:
            print('Make spectra')
        g = creategrid.gen_spectral_grid_from_stellib_given_points(osl,
                                                                   oiso.data,
                                                               bounds=bounds)

        # get the distance
        if distance is not None:
            _distance = distance.to(units.pc).value
            
        if verbose:    
            print('Adding spectral properties:', add_spectral_properties_kwargs
                  is not None)
        if add_spectral_properties_kwargs is not None:
            nameformat = add_spectral_properties_kwargs.\
                         pop('nameformat', '{0:s}') + '_nd'

        # write to disk
        # and apply the distance to the particular galaxy of interest
        # seds already at 10 pc, need multiplcation by the square of the ratio
        # to this distance
        if hasattr(g, 'writeHDF'):
            if distance is not None:
                g.seds = g.seds / (0.1 * _distance) ** 2
            if add_spectral_properties_kwargs is not None:
                g = creategrid.add_spectral_properties(g,
                                                       nameformat=nameformat,
                                            **add_spectral_properties_kwargs)
            g.writeHDF(spec_fname)
        else:
            for gk in g:
                if distance is not None:
                    gk.seds = gk.seds / (0.1 * _distance) ** 2
                if add_spectral_properties_kwargs is not None:
                    gk = creategrid.add_spectral_properties(gk,
                                              nameformat=nameformat,
                                              **add_spectral_properties_kwargs)
    
                gk.writeHDF(spec_fname, append=True)

    g = grid.FileSpectralGrid(spec_fname, backend='memory')
        
    return (spec_fname, g)

def add_stellar_priors(project, specgrid, verbose=True, **kwargs):
    """
    make_priors -- compute the weights for the stellar priors

    Parameters
    ----------
    project: str
        project name

    specgrid: grid.SpectralGrid object
        spectral grid to transform

    returns
    -------
    fname: str
       name of saved file

    g: grid.SpectralGrid object
        spectral grid to transform
    """
    priors_fname = '%s/%s_spec_w_priors.grid.hd5' % (project, project)
    if not os.path.isfile(priors_fname):

        if verbose:
            print('Make Prior Weights')

        compute_age_mass_metallicity_weights(specgrid.grid, **kwargs)

        #write to disk
        if hasattr(specgrid, 'writeHDF'):
            specgrid.writeHDF(priors_fname)
        else:
            for gk in specgrid:
                gk.writeHDF(priors_fname, append=True)

    g = grid.FileSpectralGrid(priors_fname, backend='memory')

    return (priors_fname, g)

def make_extinguished_sed_grid(project,
                               specgrid,
                               filters, 
                               av=[0., 5, 0.1], 
                               rv=[0., 5, 0.2], 
                               fA=None, 
                               av_prior_model={'name': 'flat'},
                               rv_prior_model={'name': 'flat'},
                               fA_prior_model={'name': 'flat'},
                               extLaw=None, 
                               add_spectral_properties_kwargs=None,
                               absflux_cov=False,
                               verbose=True,
                               **kwargs):
    """
    Create SED model grid integrated with filters and dust extinguished

    Parameters
    ----------
    project: str
        project name

    specgrid: grid.SpectralGrid object
        spectral grid to transform

    filters: sequence
        ordered sequence of filters to use to extract the photometry
        filter names are the full names in core.filters

    av: sequence
        sequence of Av values to sample

    av_prior_model: list
        list including prior model name and parameters

    rv: sequence
        sequence of Rv values to sample

    rv_prior_model: list
        list including prior model name and parameters

    fA: sequence (optional)
        sequence of fA values to sample (depending on extLaw definition)

    fA_prior_model: list
        list including prior model name and parameters

    extLaw: extinction.ExtLaw
        extinction law to use during the process

    add_spectral_properties_kwargs: dict
        keyword arguments to call :func:`add_spectral_properties`
        to add model properties from the spectra into the grid property table

    asbflux_cov: boolean
        set to calculate the absflux covariance matrices for each model
        (can be very slow!!!  But it is the right thing to do)

    returns
    -------
    fname: str
       name of saved file

    g: grid.SpectralGrid object
        spectral grid to transform
    """
    seds_fname = '%s/%s_seds.grid.hd5' % (project, project)
    if not os.path.isfile(seds_fname):

        extLaw = extLaw or extinction.Cardelli()

        avs = np.arange(av[0], av[1] + 0.5 * av[2], av[2])
        rvs = np.arange(rv[0], rv[1] + 0.5 * rv[2], rv[2])

        if verbose:
            print('Make SEDS')

        if fA is not None:
            fAs = np.arange(fA[0], fA[1] + 0.5 * fA[2], fA[2])
            g = creategrid.make_extinguished_grid(specgrid, filters, extLaw,
                                                  avs, 
                                                  rvs, 
                                                  fAs, 
                                                  av_prior_model=av_prior_model,
                                                  rv_prior_model=rv_prior_model,
                                                  fA_prior_model=fA_prior_model,
                add_spectral_properties_kwargs=add_spectral_properties_kwargs,
                                                  absflux_cov=absflux_cov)
        else:
            g = creategrid.make_extinguished_grid(specgrid, filters, extLaw,
                                                  avs, 
                                                  rvs,   
                                                  av_prior_model=av_prior_model,
                                                  rv_prior_model=rv_prior_model,
                  add_spectral_properties_kwargs=add_spectral_properties_kwargs,
                                                  absflux_cov=absflux_cov)

        #write to disk
        if hasattr(g, 'writeHDF'):
            g.writeHDF(seds_fname)
        else:
            for gk in g:
                gk.writeHDF(seds_fname, append=True)

    g = grid.FileSEDGrid(seds_fname, backend='hdf')
        
    return (seds_fname, g)
