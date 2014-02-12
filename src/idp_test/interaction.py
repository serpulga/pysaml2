#from commonArgs import JSON_DUMPS_ARGS
from saml2test import JSON_DUMPS_ARGS

__author__ = 'rohe0002'

import json
import logging

from urlparse import urlparse
from bs4 import BeautifulSoup

from mechanize import ParseResponseEx
from mechanize._form import ControlNotFoundError, AmbiguityError
from mechanize._form import ListControl

logger = logging.getLogger(__name__)

def pick_interaction(interactions, _base="", content="", req=None):
    unic = content
    if content:
        _bs = BeautifulSoup(content)
    else:
        _bs = None

    for interaction in interactions:
        _match = 0
        for attr, val in interaction["matches"].items():
            if attr == "url":
                if val == _base:
                    _match += 1
            elif attr == "title":
                if _bs is None:
                    break
                if _bs.title is None:
                    break
                if val in _bs.title.contents:
                    _match += 1
                else:
                    _c = _bs.title.contents
                    if isinstance(_c, list) and not isinstance(_c, basestring):
                        for _line in _c:
                            if val in _line:
                                _match += 1
                                continue
            elif attr == "content":
                if unic and val in unic:
                    _match += 1
            elif attr == "class":
                if req and val == req:
                    _match += 1

        if _match == len(interaction["matches"]):
            return interaction

    raise KeyError("No interaction matched")


class FlowException(Exception):
    def __init__(self, function="", content="", url=""):
        Exception.__init__(self)
        self.function = function
        self.content = content
        self.url = url

    def __str__(self):
        return json.dumps(self.__dict__, **JSON_DUMPS_ARGS)


class RResponse():
    """
    A Response class that behaves in the way that mechanize expects it.
    Links to a requests.Response
    """
    def __init__(self, resp):
        self._resp = resp
        self.index = 0
        self.text = resp.text
        if isinstance(self.text, unicode):
            if resp.encoding == "UTF-8":
                self.text = self.text.encode("utf-8")
            else:
                self.text = self.text.encode("latin-1")
        self._len = len(self.text)
        self.url = str(resp.url)
        self.statuscode = resp.status_code

    def geturl(self):
        return self._resp.url

    def __getitem__(self, item):
        try:
            return getattr(self._resp, item)
        except AttributeError:
            return getattr(self._resp.headers, item)

    def __getattribute__(self, item):
        try:
            return getattr(self._resp, item)
        except AttributeError:
            return getattr(self._resp.headers, item)

    def read(self, size=0):
        """
        Read from the content of the response. The class remembers what has
        been read so it's possible to read small consecutive parts of the
        content.

        :param size: The number of bytes to read
        :return: Somewhere between zero and 'size' number of bytes depending
            on how much it left in the content buffer to read.
        """
        if size:
            if self._len < size:
                return self.text
            else:
                if self._len == self.index:
                    part = None
                elif self._len - self.index < size:
                    part = self.text[self.index:]
                    self.index = self._len
                else:
                    part = self.text[self.index: self.index + size]
                    self.index += size
                return part
        else:
            return self.text


def pick_form(response, url=None, **kwargs):
    """
    Picks which form in a web-page that should be used

    :param response: A HTTP request response. A DResponse instance
    :param content: The HTTP response content
    :param url: The url the request was sent to
    :return: The picked form or None of no form matched the criteria.
    """
    #_txt = response.text

    forms = ParseResponseEx(response)
    if not forms:
        raise FlowException(content=response.text, url=url)

    #if len(forms) == 1:
    #    return forms[0]
    #else:

    _form = None
    # ignore the first form, because I use ParseResponseEx which adds
    # one form at the top of the list
    forms = forms[1:]
    if len(forms) == 1:
        _form = forms[0]
    else:
        if "pick" in kwargs:
            _dict = kwargs["pick"]
            for form in forms:
                if _form:
                    break
                for key, _ava in _dict.items():
                    if key == "form":
                        _keys = form.attrs.keys()
                        for attr, val in _ava.items():
                            if attr in _keys and val == form.attrs[attr]:
                                _form = form
                    elif key == "control":
                        prop = _ava["id"]
                        _default = _ava["value"]
                        try:
                            orig_val = form[prop]
                            if isinstance(orig_val, basestring):
                                if orig_val == _default:
                                    _form = form
                            elif _default in orig_val:
                                _form = form
                        except KeyError:
                            pass
                        except ControlNotFoundError:
                            pass
                    elif key == "method":
                        if form.method == _ava:
                            _form = form
                    else:
                        _form = None

                    if not _form:
                        break
        elif "index" in kwargs:
            _form = forms[int(kwargs["index"])]

    return _form


def do_click(httpc, form, **kwargs):
    """
    Emulates the user clicking submit on a form.

    :param httpc: The Client instance
    :param form: The form that should be submitted
    :return: What do_request() returns
    """

    if "click" in kwargs:
        request = None
        _name = kwargs["click"]
        try:
            _ = form.find_control(name=_name)
            request = form.click(name=_name)
        except AmbiguityError:
            # more than one control with that name
            _val = kwargs["set"][_name]
            _nr = 0
            while True:
                try:
                    cntrl = form.find_control(name=_name, nr=_nr)
                    if cntrl.value == _val:
                        request = form.click(name=_name, nr=_nr)
                        break
                    else:
                        _nr += 1
                except ControlNotFoundError:
                    raise Exception("No submit control with the name='%s' and "
                                    "value='%s' could be found" % (_name,
                                                                   _val))
    else:
        request = form.click()

    headers = {}
    for key, val in request.unredirected_hdrs.items():
        headers[key] = val

    url = request._Request__original

    if form.method == "POST":
        return httpc.send(url, "POST", data=request.data, headers=headers)
    else:
        return httpc.send(url, "GET", headers=headers)


def select_form(httpc, orig_response, **kwargs):
    """
    Pick a form on a web page, possibly enter some information and submit
    the form.

    :param httpc: A HTTP client instance
    :param orig_response: The original response (as returned by requests)
    :return: The response do_click() returns
    """
    response = RResponse(orig_response)
    try:
        _url = response.url
    except KeyError:
        _url = kwargs["location"]

    form = pick_form(response, _url, **kwargs)
    #form.backwards_compatible = False
    if not form:
        raise Exception("Can't pick a form !!")

    if "set" in kwargs:
        for key, val in kwargs["set"].items():
            if key.startswith("_"):
                continue
            if "click" in kwargs and kwargs["click"] == key:
                continue

            try:
                form[key] = val
            except ControlNotFoundError:
                pass
            except TypeError:
                cntrl = form.find_control(key)
                if isinstance(cntrl, ListControl):
                    form[key] = [val]
                else:
                    raise

    return do_click(httpc, form, **kwargs)


#noinspection PyUnusedLocal
def chose(httpc, orig_response, path, **kwargs):
    """
    Sends a HTTP GET to a url given by the present url and the given
    relative path.

    :param orig_response: The original response
    :param content: The content of the response
    :param path: The relative path to add to the base URL
    :return: The response do_click() returns
    """


    if not path.startswith("http"):
        try:
            _url = orig_response.url
        except KeyError:
            _url = kwargs["location"]

        part = urlparse(_url)
        url = "%s://%s%s" % (part[0], part[1], path)
    else:
        url = path

    return httpc.send(url, "GET")
    #return resp, ""


def post_form(httpc, orig_response, **kwargs):
    """
    The same as select_form but with no possibility of change the content
    of the form.

    :param httpc: A HTTP Client instance
    :param orig_response: The original response (as returned by requests)
    :param content: The content of the response
    :return: The response do_click() returns
    """
    response = RResponse(orig_response)

    form = pick_form(response, **kwargs)

    return do_click(httpc, form, **kwargs)


def NoneFunc():
    return None


#noinspection PyUnusedLocal
def parse(httpc, orig_response, **kwargs):
    # content is a form from which I get the SAMLResponse
    response = RResponse(orig_response)

    form = pick_form(response, **kwargs)
    #form.backwards_compatible = False
    if not form:
        raise Exception("Can't pick a form !!")

    return {"SAMLResponse": form["SAMLResponse"],
            "RelayState": form["RelayState"]}


#noinspection PyUnusedLocal
def interaction(args):
    _type = args["type"]
    if _type == "form":
        return select_form
    elif _type == "link":
        return chose
    elif _type == "response":
        return parse
    else:
        return NoneFunc

# ========================================================================


class Operation(object):
    def __init__(self, args=None):
        if args:
            self.function = interaction(args)

        self.args = args or {}
        self.request = None

    def update(self, dic):
        self.args.update(dic)

    #noinspection PyUnusedLocal
    def post_op(self, result, conv, args):
        pass

    def __call__(self, httpc, conv, location, response, content,
                 features):
        try:
            _args = self.args.copy()
        except (KeyError, AttributeError):
            _args = {}

        _args["location"] = location
        _args["features"] = features

        logger.info("--> FUNCTION: %s" % self.function.__name__)
        logger.info("--> ARGS: %s" % _args)

        result = self.function(httpc, response, **_args)
        self.post_op(result, conv, _args)
        return result
