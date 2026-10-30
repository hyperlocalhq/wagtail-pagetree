from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.widgets import Button

from .services.presenters import pagetree_url
from .viewsets import page_tree_viewset


@hooks.register("register_admin_viewset")
def register_pagetree_viewset():
    return page_tree_viewset


@hooks.register("register_page_header_buttons")
def page_header_buttons(page, user, view_name, next_url=None):
    """"Show in Page Tree" in the page header's actions menu.

    Opens the tree in the page's own locale with the page revealed, and
    without any search or filter left over from an earlier visit.
    """
    if page.is_root():
        return
    query = urlencode({"locale": page.locale.language_code, "clear_filters": 1})
    yield Button(
        _("Show in Page Tree"),
        f"{pagetree_url(page.id)}&{query}",
        icon_name="list-ul",
        priority=75,
    )
