"""
MikroFun Built-in TR-069 ACS Module
Handles CWMP (CPE WAN Management Protocol) communication with customer routers.
"""
from flask import Blueprint, request, Response, render_template, session, redirect, url_for, flash, jsonify
from web.database import execute_query
from web.decorators import admin_required
import xml.etree.ElementTree as ET
from datetime import datetime
import logging

acs_bp = Blueprint('acs', __name__)
logger = logging.getLogger(__name__)

# ===========================================================================
# TR-069 NAMESPACES
# ===========================================================================
NS = {
    'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
    'cwmp': 'urn:dslforum-org:cwmp-1-0',
    'xsi':  'http://www.w3.org/2001/XMLSchema-instance',
    'xsd':  'http://www.w3.org/2001/XMLSchema',
}

SOAP_ENV = 'http://schemas.xmlsoap.org/soap/envelope/'
CWMP_NS  = 'urn:dslforum-org:cwmp-1-0'

# ===========================================================================
# PARAMETER PATHS — common TR-069 paths for ONU/router management
# Supports both TR-098 (older) and TR-181 (newer)
# ===========================================================================
PARAM_SSID_24   = [
    'InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID',
    'Device.WiFi.SSID.1.SSID',
]
PARAM_SSID_50   = [
    'InternetGatewayDevice.LANDevice.1.WLANConfiguration.5.SSID',
    'Device.WiFi.SSID.2.SSID',
]
PARAM_PASS_24   = [
    'InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.PreSharedKey.1.KeyPassphrase',
    'Device.WiFi.AccessPoint.1.Security.KeyPassphrase',
]
PARAM_PASS_50   = [
    'InternetGatewayDevice.LANDevice.1.WLANConfiguration.5.PreSharedKey.1.KeyPassphrase',
    'Device.WiFi.AccessPoint.2.Security.KeyPassphrase',
]

# ===========================================================================
# XML HELPERS
# ===========================================================================
def _soap_response(body_content: str, cwmp_id: str = '1') -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope
    xmlns:soap="{SOAP_ENV}"
    xmlns:cwmp="{CWMP_NS}"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Header>
    <cwmp:ID soap:mustUnderstand="1">{cwmp_id}</cwmp:ID>
  </soap:Header>
  <soap:Body>
    {body_content}
  </soap:Body>
</soap:Envelope>"""


def _inform_response(cwmp_id: str = '1') -> str:
    return _soap_response('<cwmp:InformResponse><MaxEnvelopes>1</MaxEnvelopes></cwmp:InformResponse>', cwmp_id)


def _empty_response() -> str:
    """Sent when there are no pending tasks for the device"""
    return _soap_response('')


def _set_param_response(params: dict, cwmp_id: str = '1') -> str:
    """Build a SetParameterValues SOAP request"""
    param_list = ''
    for name, (value, vtype) in params.items():
        param_list += f"""
        <ParameterValueStruct>
          <Name>{name}</Name>
          <Value xsi:type="{vtype}">{value}</Value>
        </ParameterValueStruct>"""

    body = f"""<cwmp:SetParameterValues>
      <ParameterList soap:arrayType="cwmp:ParameterValueStruct[{len(params)}]">
        {param_list}
      </ParameterList>
      <ParameterKey>mikrofun-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}</ParameterKey>
    </cwmp:SetParameterValues>"""
    return _soap_response(body, cwmp_id)


def _reboot_response(cwmp_id: str = '1') -> str:
    return _soap_response('<cwmp:Reboot><CommandKey>mikrofun-reboot</CommandKey></cwmp:Reboot>', cwmp_id)


def _get_param_response(param_names: list, cwmp_id: str = '1') -> str:
    names_xml = ''.join(f'<string>{n}</string>' for n in param_names)
    body = f"""<cwmp:GetParameterValues>
      <ParameterNames soap:arrayType="xsd:string[{len(param_names)}]">
        {names_xml}
      </ParameterNames>
    </cwmp:GetParameterValues>"""
    return _soap_response(body, cwmp_id)


# ===========================================================================
# PARSE INFORM
# ===========================================================================
def _parse_inform(root) -> dict:
    """Extract device info from a CWMP Inform message body"""
    info = {}
    try:
        body = root.find(f'{{{SOAP_ENV}}}Body')
        inform = body.find(f'{{{CWMP_NS}}}Inform')
        if inform is None:
            return info

        di = inform.find('DeviceId')
        if di is not None:
            info['oui']    = (di.findtext('OUI') or '').strip()
            info['serial'] = (di.findtext('SerialNumber') or '').strip()
            info['model']  = (di.findtext('ProductClass') or '').strip()
            info['vendor'] = (di.findtext('Manufacturer') or '').strip()

        # Parameter values in Inform (device sends some params on check-in)
        for pv in inform.findall('.//ParameterValueStruct'):
            name  = (pv.findtext('Name') or '').strip()
            value = (pv.findtext('Value') or '').strip()
            # pick up software version
            if 'SoftwareVersion' in name or 'FirmwareVersion' in name:
                info['firmware'] = value
            if name in PARAM_SSID_24:
                info['ssid_24'] = value
            if name in PARAM_SSID_50:
                info['ssid_50'] = value

    except Exception as e:
        logger.warning(f'ACS: parse_inform error: {e}')

    return info


# ===========================================================================
# CWMP ENTRY POINT
# ===========================================================================
@acs_bp.route('/cwmp', methods=['POST', 'GET'])
def cwmp():
    """Main TR-069 ACS endpoint. Routers POST here."""
    raw = request.data

    # Empty POST = CPE is done (no more messages)
    if not raw or not raw.strip():
        return Response('', status=204)

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.error(f'ACS: XML parse error: {e}')
        return Response('Bad XML', status=400)

    body = root.find(f'{{{SOAP_ENV}}}Body')
    if body is None:
        return Response('No SOAP Body', status=400)

    # Detect method
    for child in body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag

        # ---- Inform ----
        if tag == 'Inform':
            info = _parse_inform(root)
            serial = info.get('serial', '')
            remote_ip = request.remote_addr

            if serial:
                _upsert_device(serial, info, remote_ip)

            # Get cwmp ID from header
            hdr   = root.find(f'{{{SOAP_ENV}}}Header')
            cwid  = '1'
            if hdr is not None:
                id_el = hdr.find(f'{{{CWMP_NS}}}ID')
                if id_el is not None:
                    cwid = id_el.text or '1'

            # Check for pending task
            task = _get_next_task(serial) if serial else None
            if task:
                xml_resp = _build_task_response(task, cwid)
                _mark_task_sent(task['id'])
                return Response(xml_resp, content_type='text/xml; charset=utf-8')

            return Response(_inform_response(cwid), content_type='text/xml; charset=utf-8')

        # ---- SetParameterValuesResponse ----
        elif tag == 'SetParameterValuesResponse':
            _mark_sent_task_done(request.remote_addr)
            return Response('', status=204)

        # ---- RebootResponse ----
        elif tag in ('RebootResponse', 'Fault'):
            _mark_sent_task_done(request.remote_addr)
            return Response('', status=204)

        # ---- GetParameterValuesResponse ----
        elif tag == 'GetParameterValuesResponse':
            _handle_gpv_response(root, request.remote_addr)
            return Response('', status=204)

    return Response(_empty_response(), content_type='text/xml; charset=utf-8')


# ===========================================================================
# DATABASE HELPERS
# ===========================================================================
def _upsert_device(serial: str, info: dict, remote_ip: str):
    exists = execute_query("SELECT id FROM acs_devices WHERE serial_number=%s", (serial,), fetch_one=True)
    if exists:
        execute_query(
            "UPDATE acs_devices SET model=%s, vendor=%s, firmware=%s, ip_address=%s, "
            "ssid_24=%s, ssid_50=%s, last_inform=NOW() WHERE serial_number=%s",
            (info.get('model',''), info.get('vendor',''), info.get('firmware',''),
             remote_ip, info.get('ssid_24'), info.get('ssid_50'), serial)
        )
    else:
        execute_query(
            "INSERT INTO acs_devices (serial_number, oui, model, vendor, firmware, ip_address, ssid_24, ssid_50, last_inform) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
            (serial, info.get('oui',''), info.get('model',''), info.get('vendor',''),
             info.get('firmware',''), remote_ip, info.get('ssid_24'), info.get('ssid_50'))
        )


def _get_next_task(serial: str) -> dict:
    """Return the oldest pending task for a device."""
    return execute_query(
        "SELECT * FROM acs_tasks WHERE device_serial=%s AND status='pending' ORDER BY id ASC LIMIT 1",
        (serial,), fetch_one=True
    )


def _mark_task_sent(task_id: int):
    execute_query("UPDATE acs_tasks SET status='sent', executed_at=NOW() WHERE id=%s", (task_id,))


def _mark_sent_task_done(remote_ip: str):
    """Mark the most recent 'sent' task for a device (by IP) as done."""
    dev = execute_query("SELECT serial_number FROM acs_devices WHERE ip_address=%s ORDER BY last_inform DESC LIMIT 1",
                        (remote_ip,), fetch_one=True)
    if dev:
        execute_query(
            "UPDATE acs_tasks SET status='done' WHERE device_serial=%s AND status='sent' ORDER BY id DESC LIMIT 1",
            (dev['serial_number'],)
        )


def _handle_gpv_response(root, remote_ip: str):
    """Parse GetParameterValuesResponse and store SSID info."""
    dev = execute_query("SELECT serial_number FROM acs_devices WHERE ip_address=%s ORDER BY last_inform DESC LIMIT 1",
                        (remote_ip,), fetch_one=True)
    if not dev:
        return
    serial = dev['serial_number']
    updates = {}
    for pv in root.findall('.//{%s}GetParameterValuesResponse//ParameterValueStruct' % CWMP_NS):
        name  = (pv.findtext('Name') or '').strip()
        value = (pv.findtext('Value') or '').strip()
        if name in PARAM_SSID_24: updates['ssid_24'] = value
        if name in PARAM_SSID_50: updates['ssid_50'] = value
    if updates:
        sets = ', '.join(f"{k}=%s" for k in updates)
        execute_query(f"UPDATE acs_devices SET {sets} WHERE serial_number=%s",
                      tuple(updates.values()) + (serial,))
    _mark_sent_task_done(remote_ip)


def _build_task_response(task: dict, cwid: str) -> str:
    t = task.get('task_type', '')
    v = task.get('value', '')
    param_path = task.get('param_path', '')

    if t == 'set_ssid_24':
        return _set_param_response({PARAM_SSID_24[0]: (v, 'xsd:string')}, cwid)
    elif t == 'set_ssid_50':
        return _set_param_response({PARAM_SSID_50[0]: (v, 'xsd:string')}, cwid)
    elif t == 'set_pass_24':
        return _set_param_response({PARAM_PASS_24[0]: (v, 'xsd:string')}, cwid)
    elif t == 'set_pass_50':
        return _set_param_response({PARAM_PASS_50[0]: (v, 'xsd:string')}, cwid)
    elif t == 'reboot':
        return _reboot_response(cwid)
    elif t == 'get_info':
        return _get_param_response(
            PARAM_SSID_24 + PARAM_SSID_50 + PARAM_PASS_24, cwid
        )
    elif t == 'custom_set' and param_path:
        return _set_param_response({param_path: (v, 'xsd:string')}, cwid)
    return _empty_response()


# ===========================================================================
# ADMIN API: CREATE TASK
# ===========================================================================
@acs_bp.route('/api/task', methods=['POST'])
def api_create_task():
    if not session.get('logged_in'):
        return jsonify({'error': 'unauthorized'}), 401

    serial     = request.form.get('serial', '').strip()
    task_type  = request.form.get('task_type', '').strip()
    value      = request.form.get('value', '').strip()
    param_path = request.form.get('param_path', '').strip()

    allowed = {'set_ssid_24','set_ssid_50','set_pass_24','set_pass_50','reboot','get_info','custom_set'}
    if task_type not in allowed:
        return jsonify({'error': 'invalid task_type'}), 400
    if not serial:
        return jsonify({'error': 'serial required'}), 400

    execute_query(
        "INSERT INTO acs_tasks (device_serial, task_type, value, param_path, status, created_at) "
        "VALUES (%s,%s,%s,%s,'pending',NOW())",
        (serial, task_type, value, param_path)
    )
    return jsonify({'ok': True, 'msg': f'Task {task_type} dijadwalkan untuk {serial}'})


# ===========================================================================
# ADMIN VIEWS
# ===========================================================================
@acs_bp.route('/')
def index():
    """ACS Device list — all CPEs that have checked in."""
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    devices = execute_query(
        "SELECT d.*, c.name as customer_name, c.id as customer_id "
        "FROM acs_devices d LEFT JOIN customers c ON d.customer_id=c.id "
        "ORDER BY d.last_inform DESC", fetch=True
    ) or []
    return render_template('acs/index.html', devices=devices)


@acs_bp.route('/device/<serial>')
def device_detail(serial):
    """Per-device detail and task management."""
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    device = execute_query("SELECT d.*, c.name as customer_name, c.id as customer_id "
                           "FROM acs_devices d LEFT JOIN customers c ON d.customer_id=c.id "
                           "WHERE d.serial_number=%s", (serial,), fetch_one=True)
    if not device:
        flash('Device tidak ditemukan', 'error')
        return redirect(url_for('acs.index'))
    tasks = execute_query("SELECT * FROM acs_tasks WHERE device_serial=%s ORDER BY id DESC LIMIT 30",
                          (serial,), fetch=True) or []
    customers = execute_query("SELECT id, name FROM customers ORDER BY name", fetch=True) or []
    return render_template('acs/device.html', device=device, tasks=tasks, customers=customers)


@acs_bp.route('/device/<serial>/link', methods=['POST'])
def link_customer(serial):
    """Link a CPE device to a customer."""
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    cust_id = request.form.get('customer_id') or None
    execute_query("UPDATE acs_devices SET customer_id=%s WHERE serial_number=%s", (cust_id, serial))
    flash('Device berhasil dihubungkan ke pelanggan.', 'success')
    return redirect(url_for('acs.device_detail', serial=serial))


@acs_bp.route('/settings')
def settings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    server_ip = request.host.split(':')[0]
    return render_template('acs/settings.html', server_ip=server_ip)
