# -*- coding: utf-8 -*-
import json
import logging
import os

import sqlalchemy
from flask import current_app
from flask import flash
from flask import url_for
from flask_babel import gettext

from mycodo.config import PATH_HTML_USER
from mycodo.config_translations import TRANSLATIONS
from mycodo.databases.models import Conversion
from mycodo.databases.models import Dashboard
from mycodo.databases.models import DeviceMeasurements
from mycodo.databases.models import Input
from mycodo.databases.models import Math
from mycodo.databases.models import Output
from mycodo.databases.models import PID
from mycodo.databases.models import Widget
from mycodo.mycodo_client import DaemonControl
from mycodo.mycodo_flask.extensions import db
from mycodo.mycodo_flask.utils.utils_general import custom_options_return_json
from mycodo.mycodo_flask.utils.utils_general import delete_entry_with_id
from mycodo.mycodo_flask.utils.utils_general import flash_success_errors
from mycodo.mycodo_flask.utils.utils_general import return_dependencies
from mycodo.mycodo_flask.utils.utils_general import use_unit_generate
from mycodo.utils.system_pi import assure_path_exists
from mycodo.utils.system_pi import set_user_grp
from mycodo.utils.widgets import parse_widget_information

logger = logging.getLogger(__name__)


#
# Dashboards
#

def dashboard_add():
    """Add a dashboard"""
    error = []

    last_dashboard = Dashboard.query.order_by(
        Dashboard.id.desc()).first()

    new_dash = Dashboard()
    new_dash.name = '{} {}'.format(TRANSLATIONS['dashboard']['title'], last_dashboard.id + 1)

    if not error:
        new_dash.save()

        flash(gettext(
            "Dashboard with ID %(id)s successfully added", id=new_dash.id),
            "success")

    return new_dash.unique_id


def dashboard_mod(form):
    """Modify a dashboard"""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    name_exists = Dashboard.query.filter(
        Dashboard.name == form.name.data).first()
    if name_exists:
        flash('Dashboard name already is use', 'error')
        return

    dash_mod = Dashboard.query.filter(
        Dashboard.unique_id == form.dashboard_id.data).first()
    dash_mod.name = form.name.data

    db.session.commit()

    flash_success_errors(
        error, action, url_for('routes_page.page_dashboard_default'))


def dashboard_del(form):
    """Delete a dashboard"""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    dashboards = Dashboard.query.all()
    if len(dashboards) == 1:
        flash('Cannot delete the only remaining dashboard.', 'error')
        return

    widgets = Widget.query.filter(
        Widget.dashboard_id == form.dashboard_id.data).all()
    for each_widget in widgets:
        delete_entry_with_id(Widget, each_widget.unique_id)

    delete_entry_with_id(Dashboard, form.dashboard_id.data)

    flash_success_errors(
        error, action, url_for('routes_page.page_dashboard_default'))


#
# Widgets
#

def widget_add(form_base, request_form):
    """Add a widget to the dashboard"""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    dict_widgets = parse_widget_information()

    if form_base.widget_type.data:
        widget_name = form_base.widget_type.data
    else:
        widget_name = ''
        error.append("Missing widget name")

    if current_app.config['TESTING']:
        dep_unmet = False
    else:
        dep_unmet, _ = return_dependencies(widget_name)
        if dep_unmet:
            list_unmet_deps = []
            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[0])
            error.append("The {dev} device you're trying to add has unmet dependencies: {dep}".format(
                dev=widget_name, dep=', '.join(list_unmet_deps)))

    new_widget = Widget()
    new_widget.dashboard_id = form_base.dashboard_id.data
    new_widget.graph_type = widget_name
    new_widget.name = form_base.name.data
    new_widget.font_em_name = form_base.font_em_name.data
    new_widget.enable_drag_handle = form_base.enable_drag_handle.data
    new_widget.refresh_duration = form_base.refresh_duration.data

    # Find where the next widget should be placed on the grid
    # Finds the lowest position to create as the new Widget's starting position
    position_y_start = 0
    for each_widget in Widget.query.filter(
            Widget.dashboard_id == form_base.dashboard_id.data).all():
        highest_position = each_widget.position_y + each_widget.height
        if highest_position > position_y_start:
            position_y_start = highest_position
    new_widget.position_y = position_y_start

    # widget add options
    if widget_name in dict_widgets:
        def dict_has_value(key):
            if (key in dict_widgets[widget_name] and
                    (dict_widgets[widget_name][key] or dict_widgets[widget_name][key] == 0)):
                return True

        if dict_has_value('widget_width'):
            new_widget.width = dict_widgets[widget_name]['widget_width']
        if dict_has_value('widget_height'):
            new_widget.height = dict_widgets[widget_name]['widget_height']

    # Generate string to save from custom options
    error, custom_options = custom_options_return_json(
        error, dict_widgets, request_form, device=widget_name)
    new_widget.custom_options = custom_options

    #
    # Execute at Creation
    #

    if 'execute_at_creation' in dict_widgets[widget_name] and not current_app.config['TESTING']:
        dict_widgets[widget_name]['execute_at_creation'](
            new_widget, dict_widgets[widget_name])

    try:
        if not error:
            new_widget.save()

            #
            # Save HTML files
            #
            assure_path_exists(PATH_HTML_USER)

            filename_head = "widget_template_{}_head.html".format(widget_name)
            path_head = os.path.join(PATH_HTML_USER, filename_head)
            with open(path_head, 'w') as fw:
                if 'widget_dashboard_head' in dict_widgets[widget_name]:
                    html_head = dict_widgets[widget_name]['widget_dashboard_head']
                else:
                    html_head = ""
                fw.write(html_head)
                fw.close()
            set_user_grp(path_head, 'mycodo', 'mycodo')

            filename_title_bar = "widget_template_{}_title_bar.html".format(widget_name)
            path_title_bar = os.path.join(PATH_HTML_USER, filename_title_bar)
            with open(path_title_bar, 'w') as fw:
                if 'widget_dashboard_title_bar' in dict_widgets[widget_name]:
                    html_title_bar = dict_widgets[widget_name]['widget_dashboard_title_bar']
                else:
                    html_title_bar = ""
                fw.write(html_title_bar)
                fw.close()
            set_user_grp(path_title_bar, 'mycodo', 'mycodo')

            filename_body = "widget_template_{}_body.html".format(widget_name)
            path_body = os.path.join(PATH_HTML_USER, filename_body)
            with open(path_body, 'w') as fw:
                if 'widget_dashboard_body' in dict_widgets[widget_name]:
                    html_body = dict_widgets[widget_name]['widget_dashboard_body']
                else:
                    html_body = ""
                fw.write(html_body)
                fw.close()
            set_user_grp(path_body, 'mycodo', 'mycodo')

            filename_configure_options = "widget_template_{}_configure_options.html".format(widget_name)
            path_configure_options = os.path.join(PATH_HTML_USER, filename_configure_options)
            with open(path_configure_options, 'w') as fw:
                if 'widget_dashboard_configure_options' in dict_widgets[widget_name]:
                    html_configure_options = dict_widgets[widget_name]['widget_dashboard_configure_options']
                else:
                    html_configure_options = ""
                fw.write(html_configure_options)
                fw.close()
            set_user_grp(path_configure_options, 'mycodo', 'mycodo')

            filename_js = "widget_template_{}_js.html".format(widget_name)
            path_js = os.path.join(PATH_HTML_USER, filename_js)
            with open(path_js, 'w') as fw:
                if 'widget_dashboard_js' in dict_widgets[widget_name]:
                    html_js = dict_widgets[widget_name]['widget_dashboard_js']
                else:
                    html_js = ""
                fw.write(html_js)
                fw.close()
            set_user_grp(path_js, 'mycodo', 'mycodo')

            filename_js_ready = "widget_template_{}_js_ready.html".format(widget_name)
            path_js_ready = os.path.join(PATH_HTML_USER, filename_js_ready)
            with open(path_js_ready, 'w') as fw:
                if 'widget_dashboard_js_ready' in dict_widgets[widget_name]:
                    html_js_ready = dict_widgets[widget_name]['widget_dashboard_js_ready']
                else:
                    html_js_ready = ""
                fw.write(html_js_ready)
                fw.close()
            set_user_grp(path_js_ready, 'mycodo', 'mycodo')

            filename_js_ready_end = "widget_template_{}_js_ready_end.html".format(widget_name)
            path_js_ready_end = os.path.join(PATH_HTML_USER, filename_js_ready_end)
            with open(path_js_ready_end, 'w') as fw:
                if 'widget_dashboard_js_ready_end' in dict_widgets[widget_name]:
                    html_js_ready_end = dict_widgets[widget_name]['widget_dashboard_js_ready_end']
                else:
                    html_js_ready_end = ""
                fw.write(html_js_ready_end)
                fw.close()
            set_user_grp(path_js_ready_end, 'mycodo', 'mycodo')

            # Refresh widget settings
            control = DaemonControl()
            control.widget_add_refresh(new_widget.unique_id)

            flash(gettext(
                "{dev} with ID %(id)s successfully added".format(
                    dev=dict_widgets[form_base.widget_type.data]['widget_name']),
                id=new_widget.id),
                "success")
    except sqlalchemy.exc.OperationalError as except_msg:
        error.append(except_msg)
    except sqlalchemy.exc.IntegrityError as except_msg:
        error.append(except_msg)

    return dep_unmet


def widget_mod(form_base, request_form):
    """Modify the settings of an item on the dashboard"""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    dict_widgets = parse_widget_information()

    mod_widget = Widget.query.filter(
        Widget.unique_id == form_base.widget_id.data).first()
    mod_widget.name = form_base.name.data
    mod_widget.font_em_name = form_base.font_em_name.data
    mod_widget.enable_drag_handle = form_base.enable_drag_handle.data
    mod_widget.refresh_duration = form_base.refresh_duration.data

    custom_options_json_presave = json.loads(mod_widget.custom_options)

    # Generate string to save from custom options
    error, custom_options_json_postsave = custom_options_return_json(
        error, dict_widgets, request_form, device=mod_widget.graph_type)

    if 'execute_at_modification' in dict_widgets[mod_widget.graph_type]:
        (allow_saving,
         mod_input,
         custom_options) = dict_widgets[mod_widget.graph_type]['execute_at_modification'](
            mod_widget, request_form, custom_options_json_presave, json.loads(custom_options_json_postsave))
        custom_options = json.dumps(custom_options)  # Convert from dict to JSON string
        if not allow_saving:
            error.append("execute_at_modification() would not allow widget options to be saved")
    else:
        custom_options = custom_options_json_postsave

    mod_widget.custom_options = custom_options

    if not error:
        try:
            db.session.commit()
        except sqlalchemy.exc.OperationalError as except_msg:
            error.append(except_msg)
        except sqlalchemy.exc.IntegrityError as except_msg:
            error.append(except_msg)

        control = DaemonControl()
        control.widget_add_refresh(mod_widget.unique_id)

    flash_success_errors(error, action, url_for(
        'routes_page.page_dashboard',
        dashboard_id=form_base.dashboard_id.data))


def widget_del(form_base):
    """Delete a widget from a dashboard"""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    dict_widgets = parse_widget_information()
    widget = Widget.query.filter(
        Widget.unique_id == form_base.widget_id.data).first()

    try:
        if 'execute_at_deletion' in dict_widgets[widget.graph_type]:
            dict_widgets[widget.graph_type]['execute_at_deletion'](form_base.widget_id.data)
    except Exception as except_msg:
        error.append(except_msg)

    try:
        delete_entry_with_id(Widget, form_base.widget_id.data)

        control = DaemonControl()
        control.widget_remove(form_base.widget_id.data)
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_page.page_dashboard',
                               dashboard_id=form_base.dashboard_id.data))


def graph_y_axes_async(dict_measurements, ids_measures):
    """ Determine which y-axes to use for each Graph """
    if not ids_measures:
        return

    y_axes = []

    device_measurements = DeviceMeasurements.query.all()
    input_dev = Input.query.all()
    math = Math.query.all()
    output = Output.query.all()
    pid = PID.query.all()

    devices_list = [input_dev, math, output, pid]

    # Iterate through device tables
    for each_device in devices_list:

        # Iterate through each set of ID and measurement of the dashboard element
        for each_id_measure in ids_measures:

            if each_device != output and ',' in each_id_measure:
                measure_id = each_id_measure.split(',')[1]

                for each_measure in device_measurements:
                    if each_measure.unique_id == measure_id:

                        if each_measure.conversion_id:
                            conversion = Conversion.query.filter(
                                Conversion.unique_id == each_measure.conversion_id).first()
                            if not y_axes:
                                y_axes = [conversion.convert_unit_to]
                            elif y_axes and conversion.convert_unit_to not in y_axes:
                                y_axes.append(conversion.convert_unit_to)
                        elif (each_measure.rescaled_measurement and
                                each_measure.rescaled_unit):
                            if not y_axes:
                                y_axes = [each_measure.rescaled_unit]
                            elif y_axes and each_measure.rescaled_unit not in y_axes:
                                y_axes.append(each_measure.rescaled_unit)
                        else:
                            if not y_axes:
                                y_axes = [each_measure.unit]
                            elif y_axes and each_measure.unit not in y_axes:
                                y_axes.append(each_measure.unit)

            elif each_device == output and ',' in each_id_measure:
                output_id = each_id_measure.split(',')[0]

                for each_output in output:
                    if each_output.unique_id == output_id:
                        if not y_axes:
                            y_axes = [each_output.unit]
                        elif y_axes and each_output.unit not in y_axes:
                            y_axes.append(each_output.unit)

            if len(each_id_measure.split(',')) > 1 and each_id_measure.split(',')[1].startswith('channel_'):
                unit = each_id_measure.split(',')[1].split('_')[4]

                if not y_axes:
                    y_axes = [unit]
                elif y_axes and unit not in y_axes:
                    y_axes.append(unit)

            else:
                if len(each_id_measure.split(',')) == 2:

                    unique_id = each_id_measure.split(',')[0]
                    measurement = each_id_measure.split(',')[1]

                    # Iterate through each device entry
                    for each_device_entry in each_device:

                        # If the ID saved to the dashboard element matches the table entry ID
                        if each_device_entry.unique_id == unique_id:

                            y_axes = check_func(each_device,
                                                unique_id,
                                                y_axes,
                                                measurement,
                                                dict_measurements,
                                                device_measurements,
                                                input_dev,
                                                output,
                                                math)

                elif len(each_id_measure.split(',')) == 3:

                    unique_id = each_id_measure.split(',')[0]
                    measurement = each_id_measure.split(',')[1]
                    unit = each_id_measure.split(',')[2]

                    # Iterate through each device entry
                    for each_device_entry in each_device:

                        # If the ID saved to the dashboard element matches the table entry ID
                        if each_device_entry.unique_id == unique_id:

                            y_axes = check_func(each_device,
                                                unique_id,
                                                y_axes,
                                                measurement,
                                                dict_measurements,
                                                device_measurements,
                                                input_dev,
                                                output,
                                                math,
                                                unit=unit)

    return y_axes


def check_func(all_devices,
               unique_id,
               y_axes,
               measurement,
               dict_measurements,
               device_measurements,
               input_dev,
               output,
               math,
               unit=None):
    """
    Generate a list of y-axes for Live and Asynchronous Graphs
    :param all_devices: Input, Math, Output, and PID SQL entries of a table
    :param unique_id: The ID of the measurement
    :param y_axes: empty list to populate
    :param measurement:
    :param dict_measurements:
    :param device_measurements:
    :param input_dev:
    :param output:
    :param math:
    :param unit:
    :return: None
    """
    # Iterate through each device entry
    for each_device in all_devices:

        # If the ID saved to the dashboard element matches the table entry ID
        if each_device.unique_id == unique_id:

            use_unit = use_unit_generate(
                device_measurements, input_dev, output, math)

            # Add duration
            if measurement == 'duration_time':
                if 'second' not in y_axes:
                    y_axes.append('second')

            # Add duty cycle
            elif measurement == 'duty_cycle':
                if 'percent' not in y_axes:
                    y_axes.append('percent')

            # Use custom-converted units
            elif (unique_id in use_unit and
                    measurement in use_unit[unique_id] and
                    use_unit[unique_id][measurement]):
                measure_short = use_unit[unique_id][measurement]
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # Find the y-axis the setpoint or bands apply to
            elif measurement in ['setpoint', 'setpoint_band_min', 'setpoint_band_max']:
                for each_input in input_dev:
                    if each_input.unique_id == each_device.measurement.split(',')[0]:
                        pid_measurement = each_device.measurement.split(',')[1]

                        # If PID uses input with custom conversion, use custom unit
                        if (each_input.unique_id in use_unit and
                                pid_measurement in use_unit[each_input.unique_id] and
                                use_unit[each_input.unique_id][pid_measurement]):
                            measure_short = use_unit[each_input.unique_id][pid_measurement]
                            if measure_short not in y_axes:
                                y_axes.append(measure_short)
                        # Else use default unit for input measurement
                        else:
                            if pid_measurement in dict_measurements:
                                measure_short = dict_measurements[pid_measurement]['meas']
                                if measure_short not in y_axes:
                                    y_axes.append(measure_short)

            # Append all other measurements if they don't already exist
            elif measurement in dict_measurements and not unit:
                measure_short = dict_measurements[measurement]['meas']
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # use custom y-axis
            elif measurement not in dict_measurements or unit not in dict_measurements[measurement]['units']:
                meas_name = '{meas}_{un}'.format(meas=measurement, un=unit)
                if meas_name not in y_axes and unit:
                    y_axes.append(meas_name)

    return y_axes
