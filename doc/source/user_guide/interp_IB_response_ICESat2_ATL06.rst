===================================
interp_IB_response_ICESat2_ATL06.py
===================================

- Calculates inverse-barometer (IB) responses for correcting ICESat-2 land ice elevation data [Wunsch1997]_ [HofmannWellenhof2006]_
- Can use mean sea level pressure outputs from `ERA-Interim <http://apps.ecmwf.int/datasets/data/interim-full-moda>`_, `ERA5 <http://apps.ecmwf.int/data-catalogues/era5/?class=ea>`_ and `MERRA-2 <https://gmao.gsfc.nasa.gov/reanalysis/MERRA-2/>`_ reanalyses

`Source code`__

.. __: https://github.com/tsutterley/Grounding-Zones/blob/main/DAC/interp_IB_response_ICESat2_ATL06.py

Calling Sequence
################

.. argparse::
    :filename: ../../DAC/interp_IB_response_ICESat2_ATL06.py
    :func: arguments
    :prog: interp_IB_response_ICESat2_ATL06.py
    :nodescription:
    :nodefault:

    --density -d : @replace
        Density of seawater in kg/m\ :sup:`3`

References
##########

.. [Wunsch1997] C. Wunsch and D. Stammer, "Atmospheric loading and the oceanic "inverted barometer" effect", *Reviews of Geophysics*, 35(1), 79-107, (1997). `doi:10.1029/96RG03037 <https://doi.org/10.1029/96RG03037>`_

.. [HofmannWellenhof2006] B. Hofmann-Wellenhof and H. Moritz, *Physical Geodesy*, 2nd Edition, 403 pp., (2006). `doi: 10.1007/978-3-211-33545-1 <https://doi.org/10.1007/978-3-211-33545-1>`_
