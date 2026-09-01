from django.contrib.admin import AdminSite


class OrigoAdminSite(AdminSite):
    """Admin startsida som ordnar modeller efter produktområde."""

    site_header = 'Origo administration'
    site_title = 'Origo admin'
    index_title = 'Administration'
    index_template = 'admin/index.html'

    app_order = ('accounts', 'flux', 'verso', 'tempus', 'apsis')
    app_names = {
        'accounts': 'Användare & åtkomst',
        'flux': 'Flux – projekt & planering',
        'verso': 'Verso – boenden & bokningar',
        'tempus': 'Tempus – arter & observationer',
        'apsis': 'Apsis – inlägg',
    }

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)

        for app in app_list:
            app['name'] = self.app_names.get(app['app_label'], app['name'])
            app['models'].sort(key=lambda model: model['name'])

        app_list.sort(
            key=lambda app: self.app_order.index(app['app_label'])
            if app['app_label'] in self.app_order
            else len(self.app_order)
        )
        return app_list


site = OrigoAdminSite(name='admin')
