from django.urls import path
from django.utils.translation import gettext_lazy as _
from django.views.i18n import JavaScriptCatalog
from wagtail.admin.viewsets.base import ViewSet

from .views import (
    BulkActionView,
    ChildrenAPIView,
    MoveActionView,
    PageTreeView,
    TreeAPIView,
)


class PageTreeViewSet(ViewSet):
    name = "pagetree"
    icon = "list-ul"
    menu_label = _("Page Tree")
    menu_order = 110
    add_to_admin_menu = True

    def get_urlpatterns(self):
        return [
            path("", PageTreeView.as_view(), name="index"),
            path("api/tree/", TreeAPIView.as_view(), name="api-tree"),
            path(
                "api/children/<int:page_id>/",
                ChildrenAPIView.as_view(),
                name="api-children",
            ),
            path("api/bulk/", BulkActionView.as_view(), name="api-bulk"),
            path("api/move/", MoveActionView.as_view(), name="api-move"),
            path(
                "jsi18n/",
                JavaScriptCatalog.as_view(packages=["wagtail_pagetree"]),
                name="jsi18n",
            ),
        ]


page_tree_viewset = PageTreeViewSet()
