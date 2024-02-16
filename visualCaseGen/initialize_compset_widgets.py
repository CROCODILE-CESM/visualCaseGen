import logging
import ipywidgets as widgets

from ProConPy.config_var import cvars

logger = logging.getLogger("\t" + __name__.split(".")[-1])

description_width = "160px"

def initialize_compset_widgets(cime):
    """Construct the compset section of the GUI."""

    cv_compset_mode = cvars["COMPSET_MODE"]
    cv_compset_mode.widget = widgets.ToggleButtons(
        description="Compset Selection Mode:",
        layout={"display": "flex", "width": "max-content", "padding": "10px"},
        style = {'button_width':'100px', 'description_width':description_width},
        disabled=False,
    )

    cv_inittime = cvars['INITTIME']
    cv_inittime.widget = widgets.ToggleButtons(
        description='Initialization Time:',
        layout={'display':'flex', 'width': 'max-content', 'padding':'10px'},
        style = {'button_width':'100px', 'description_width':description_width},
        disabled=False
    )

    for comp_class in cime.comp_classes:

        cv_comp = cvars['COMP_{}'.format(comp_class)]
        cv_comp.widget = widgets.ToggleButtons(
            layout = {'width':'120px', 'max_height':'145px'},
            style = {'button_width':'105px', 'description_width':'0px'},
            disabled=False,
        )