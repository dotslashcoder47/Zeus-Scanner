import os
import re
try:
    import urlparse  # python 2
except ImportError:
    import urllib.parse as urlparse  # python 3
import tempfile
import importlib

import requests

from lib.errors import InvalidTamperProvided
from lib.settings import (
    logger,
    set_color,
    DEFAULT_USER_AGENT,
    proxy_string_to_dict,
    DBMS_ERRORS,
    create_tree,
    prompt,
    shutdown
)


def list_tamper_scripts(path="{}/lib/attacks/tamper_scripts"):
    retval = set()
    exclude = ["__init__.py", ".pyc"]
    for item in os.listdir(path.format(os.getcwd())):
        if not any(f in item for f in exclude):
            item = item.split(".")[0]
            item = item.split("_")[0]
            retval.add(item)
    return retval


def __tamper_payload(payload, tamper_type, warning=True, **kwargs):
    acceptable = list_tamper_scripts()
    tamper_name = "lib.attacks.tamper_scripts.{}_encode"
    if tamper_type in acceptable:
        tamper_script = importlib.import_module(tamper_name.format(tamper_type))
        return tamper_script.tamper(payload, warning=warning)
    else:
        raise InvalidTamperProvided()


def __load_payloads(filename="{}/etc/xss_payloads.txt"):
    with open(filename.format(os.getcwd())) as payloads: return payloads.readlines()


def create_urls(url, payload_list, tamper=None):
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf_name = tf.name
    with tf as tmp:
        for i, payload in enumerate(payload_list):
            if tamper:
                try:
                    if i < 1:
                        payload = __tamper_payload(payload, tamper_type=tamper, warning=True)
                    else:
                        payload = __tamper_payload(payload, tamper_type=tamper, warning=False)
                except InvalidTamperProvided:
                    logger.error(set_color(
                        "you provided and invalid tamper script, acceptable tamper scripts are: {}...".format(
                            " | ".join(list_tamper_scripts()), level=40
                        )
                    ))
                    shutdown()
            loaded_url = "{}{}\n".format(url.strip(), payload.strip())
            tmp.write(loaded_url)
    return tf_name


def find_xss_script(url, query=4, fragment=5):
    data = urlparse.urlparse(url)
    if data[fragment] is not "" or None:
        return "{}{}".format(data[query], data[fragment])
    else:
        return data[query]


def scan_xss(url, agent=None, proxy=None):
    user_agent = agent or DEFAULT_USER_AGENT
    config_proxy = proxy_string_to_dict(proxy)
    config_headers = {"connection": "close", "user-agent": user_agent}
    xss_request = requests.get(url, proxies=config_proxy, headers=config_headers)
    html_data = xss_request.content
    query = find_xss_script(url)
    for db in DBMS_ERRORS.keys():
        for item in DBMS_ERRORS[db]:
            if re.findall(item, html_data):
                return "sqli", db
    if query in html_data:
        return True, None
    return False, None


def main_xss(start_url, verbose=False, proxy=None, agent=None, tamper=None):
    if tamper:
        logger.info(set_color(
            "tampering payloads with '{}'...".format(tamper)
        ))
    find_xss_script(start_url)
    logger.info(set_color(
        "loading payloads..."
    ))
    payloads = __load_payloads()
    if verbose:
        logger.debug(set_color(
            "a total of {} payloads loaded...".format(len(payloads)), level=10
        ))
    logger.info(set_color(
        "payloads will be written to a temporary file and read from there..."
    ))
    filename = create_urls(start_url, payloads, tamper=tamper)
    logger.info(set_color(
            "loaded URL's have been saved to '{}'...".format(filename)
        ))
    logger.info(set_color(
        "testing for XSS vulnerabilities on host '{}'...".format(start_url)
    ))
    if proxy is not None:
        logger.info(set_color(
            "using proxy '{}'...".format(proxy)
        ))
    success = set()
    with open(filename) as urls:
        for i, url in enumerate(urls.readlines(), start=1):
            url = url.strip()
            result = scan_xss(url, proxy=proxy, agent=agent)
            payload = find_xss_script(url)
            if verbose:
                logger.info(set_color(
                    "trying payload '{}'...".format(payload)
                ))
            if result[0] != "sqli" and result[0] is True:
                success.add(url)
                if verbose:
                    logger.debug(set_color(
                        "payload '{}' appears to be usable...".format(payload), level=10
                    ))
            elif result[0] is "sqli":
                if i <= 1:
                    logger.error(set_color(
                        "loaded URL '{}' threw a DBMS error and appears to be injectable, test for SQL injection, "
                        "backend DBMS appears to be '{}'...".format(
                            url, result[1]
                        ), level=40
                    ))
                else:
                    if verbose:
                        logger.error(set_color(
                            "SQL error discovered...", level=40
                        ))
            else:
                if verbose:
                    logger.debug(set_color(
                        "host '{}' does not appear to be vulnerable to XSS attacks with payload '{}'...".format(
                            start_url, payload
                        ), level=10
                    ))
    if len(success) != 0:
        logger.info(set_color(
            "possible XSS scripts to be used:"
        ))
        create_tree(start_url, list(success))
    else:
        logger.error(set_color(
            "host '{}' does not appear to be vulnerable to XSS attacks...".format(start_url)
        ))
    save = prompt(
        "would you like to keep the URL's saved for further testing", opts="yN"
    )
    if save.lower().startswith("n"):
        os.remove(filename)