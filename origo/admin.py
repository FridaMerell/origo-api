from django.contrib.admin import AdminSite


class OrigoAdminSite(AdminSite):
    """Admin startsida som ordnar modeller efter produktområde.

    En app med många modeller (t.ex. tempus) kan bli en lång, odifferentierad
    lista att leta igenom. ``model_groups`` delar en apps modeller in i
    namngivna underrubriker på startsidan istället - se ``index.html``. En
    app utan egen post i ``model_groups`` visar sin flata, alfabetiska lista
    som tidigare.
    """

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
    # app_label -> ordered [(group name, [Model class name, ...]), ...].
    # A model not listed for its app falls into a trailing "Övrigt" group so
    # nothing silently disappears from the index when a new model is added
    # without also being placed here.
    model_groups = {
        'tempus': (
            ('Arter & fenologi', ('SpeciesCategory', 'Species', 'Phenophase', 'Phenogram')),
            ('Checklistor & observationer', ('Checklist', 'ChecklistItem', 'Observation')),
            ('Platser & kartdata', ('GeoArea', 'Source', 'LandCoverFetch')),
            ('BirdNET', ('BirdnetDevice',)),
        ),
    }

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)

        for app in app_list:
            app['name'] = self.app_names.get(app['app_label'], app['name'])
            app['models'].sort(key=lambda model: model['name'])

            groups = self.model_groups.get(app['app_label'])
            if groups:
                app['groups'] = self._grouped_models(app['models'], groups)

        app_list.sort(
            key=lambda app: self.app_order.index(app['app_label'])
            if app['app_label'] in self.app_order
            else len(self.app_order)
        )
        return app_list

    @staticmethod
    def _grouped_models(models, groups):
        by_object_name = {model['object_name']: model for model in models}
        grouped = []
        seen = set()
        for group_name, object_names in groups:
            group_models = [
                by_object_name[name] for name in object_names if name in by_object_name
            ]
            seen.update(object_names)
            if group_models:
                grouped.append({'name': group_name, 'models': group_models})
        leftover = [model for model in models if model['object_name'] not in seen]
        if leftover:
            grouped.append({'name': 'Övrigt', 'models': leftover})
        return grouped


site = OrigoAdminSite(name='admin')
