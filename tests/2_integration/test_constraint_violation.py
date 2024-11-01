#!/usr/bin/env python3
import os
import time
import pytest
from pathlib import Path

from ProConPy.config_var import ConfigVar, cvars
from ProConPy.stage import Stage
from ProConPy.dev_utils import ConstraintViolation
from ProConPy.csp_solver import csp
from visualCaseGen.cime_interface import CIME_interface
from visualCaseGen.initialize_configvars import initialize_configvars
from visualCaseGen.initialize_widgets import initialize_widgets
from visualCaseGen.initialize_stages import initialize_stages
from visualCaseGen.specs.options import set_options
from visualCaseGen.specs.relational_constraints import get_relational_constraints


# do not show logger output
import logging
logger = logging.getLogger()
logger.setLevel(logging.CRITICAL)

temp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'temp'))

def test_constraint_violation_detection():
    """Confirm relational constraint violations are caught for the custom compset configuration."""

    ConfigVar.reboot()
    Stage.reboot()
    cime = CIME_interface()
    initialize_configvars(cime)
    initialize_widgets(cime) 
    initialize_stages(cime) 
    set_options(cime)
    csp.initialize(cvars, get_relational_constraints(cvars), Stage.first())

    start = time.time()

    assert Stage.first().enabled
    cvars['COMPSET_MODE'].value = 'Custom'
    cvars['INITTIME'].value = '2000'

    # Component selection

    cvars['COMP_ATM'].value = "cam"

    with pytest.raises(ConstraintViolation):
        # CAM cannot be coupled with Data ICE
        cvars['COMP_ICE'].value = "dice"

    cvars['COMP_LND'].value = "clm"

    cvars['COMP_ICE'].value = "cice"
    with pytest.raises(ConstraintViolation):
        # to enable CICE, must pick an active/data ocn
        cvars['COMP_OCN'].value = "socn"
    
    cvars['COMP_ICE'].value = "sice"
    cvars['COMP_OCN'].value = "socn"

    with pytest.raises(ConstraintViolation):
        # cannot couple stub ocn with active wave
        cvars['COMP_WAV'].value = "ww3"
    assert cvars['COMP_WAV'].value == None

    cvars['COMP_OCN'].value = "mom"
    cvars['COMP_ICE'].value = "cice"

    with pytest.raises(ConstraintViolation):
        # MOM6 cannot be coupled with data wave component
        cvars['COMP_WAV'].value = "dwav"
    assert cvars['COMP_WAV'].value == None

    cvars['COMP_ROF'].value = "mosart"
    with pytest.raises(ConstraintViolation):
        # MOSART cannot be run with slim
        cvars['COMP_LND'].value = "slim"
    assert cvars['COMP_LND'].value == "clm"

    cvars['COMP_GLC'].value = "sglc"
    cvars['COMP_WAV'].value = "ww3"

    # Component physics
    assert Stage.active().title.startswith('Component Physics')

    cvars['COMP_ATM_PHYS'].value = "CAM60"
    cvars['COMP_LND_PHYS'].value = "CLM50"

    # Component options
    assert Stage.active().title.startswith('Component Options')
    cvars['COMP_ATM_OPTION'].value = "(none)"

    with pytest.raises(ConstraintViolation):
        # must pick a valid CLM option
        cvars['COMP_LND_OPTION'].value = "(none)"
    cvars['COMP_LND_OPTION'].value = "SP"

    cvars['COMP_ICE_OPTION'].value = "(none)"
    cvars['COMP_OCN_OPTION'].value = "(none)"
    cvars['COMP_ROF_OPTION'].value = "(none)"

    # Grid
    assert Stage.active().title.startswith('2. Grid')
    cvars['GRID_MODE'].value = 'Custom'
    assert Stage.active().title.startswith('Custom Grid')

    custom_grid_path = Path(temp_dir) / "custom_grid"
    cvars['CUSTOM_GRID_PATH'].value = str(custom_grid_path)

    # Set the atmosphere grid
    assert Stage.active().title.startswith('Atm')
    cvars['CUSTOM_ATM_GRID'].value = "TL319"

    # Set the custom ocean grid mode
    assert Stage.active().title.startswith('Ocean')
    cvars['OCN_GRID_MODE'].value = "Create New"

    # Set the custom ocean grid properties
    assert Stage.active().title.startswith('Custom Ocean')
    cvars['OCN_GRID_EXTENT'].value = "Global"
    with pytest.raises(ConstraintViolation):
        cvars['OCN_CYCLIC_X'].value = "False"
    cvars['OCN_NX'].value = 100
    cvars['OCN_NY'].value = 50
    with pytest.raises(ConstraintViolation):
        cvars['OCN_LENX'].value = 10.0
    cvars['OCN_LENX'].value = 360.0
    with pytest.raises(ConstraintViolation):
        cvars['OCN_LENY'].value = 181.0
    cvars['OCN_LENY'].value = 180.0
    cvars['CUSTOM_OCN_GRID_NAME'].value = "test_grid"

    elapsed = time.time() - start
    print(f"Elapsed time: {elapsed:.3f}")


def test_multiple_reasons():
    """Check if the csp solver can catch constraint violation due to combinations of multiple reasons."""

    ConfigVar.reboot()
    Stage.reboot()
    cime = CIME_interface()
    initialize_configvars(cime)
    initialize_widgets(cime) 
    initialize_stages(cime) 
    set_options(cime)
    csp.initialize(cvars, get_relational_constraints(cvars), Stage.first())

    assert Stage.first().enabled
    cvars['COMPSET_MODE'].value = 'Custom'
    cvars['INITTIME'].value = '2000'

    assert Stage.active().title.startswith('Components')

    cvars['COMP_ICE'].value = "cice"
    cvars['COMP_ROF'].value = "mosart"

    # Combination of two reasons
    with pytest.raises(ConstraintViolation) as exc_info:
        cvars['COMP_ATM'].value = "datm"
    err_msg = str(exc_info.value)
    assert "Active runoff models can only be selected if CLM is the land component." in err_msg
    assert "If CLM is coupled with DATM, then both ICE and OCN must be stub." in err_msg

    # Reset active stage
    Stage.active().reset()
    cvars['COMP_ATM'].value = "cam"
    cvars['COMP_ROF'].value = "drof"
    cvars['COMP_WAV'].value = "dwav"

    # Combination of four reasons
    with pytest.raises(ConstraintViolation) as exc_info:
        cvars['COMP_GLC'].value = "cism"
    err_msg = str(exc_info.value)
    assert "CLM cannot be coupled with a data runoff model" in err_msg
    assert "MOM6 cannot be coupled with data wave component" in err_msg
    assert "GLC cannot be coupled with a stub land model, unless it is coupled with MOM6" in err_msg
    assert "CAM-DLND coupling is not supported" in err_msg

if __name__ == "__main__":
    test_constraint_violation_detection()
    test_multiple_reasons()

