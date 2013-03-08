# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Guewen Baconnier
#    Copyright 2013 Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
import openerp.addons.connector as connector
from ..backend import magento

_logger = logging.getLogger(__name__)


class MagentoImportSynchronizer(connector.ImportSynchronizer):
    """ Base importer for Magento """

    def __init__(self, environment):
        """
        :param environment: current environment (backend, session, ...)
        :type environment: :py:class:`connector.connector.Environment`
        """
        super(MagentoImportSynchronizer, self).__init__(environment)
        self.magento_id = None
        self.magento_record = None

    def _get_magento_data(self):
        """ Return the raw Magento data for ``self.magento_id`` """
        return self.backend_adapter.read(self.magento_id)

    def _has_to_skip(self):
        """ Return True if the import can be skipped """
        return False

    def _import_dependencies(self):
        """ Import the dependencies for the record"""
        return

    def _map_data(self):
        """ Return the external record converted to OpenERP """
        return self.mapper.convert(self.magento_record)

    def _validate_data(self, data):
        """ Check if the values to import are correct

        Pro-actively check before the ``Model.create`` or
        ``Model.update`` if some fields are missing

        Raise `InvalidDataError`
        """
        return

    def _create(self, data):
        """ Create the OpenERP record """
        context = dict(self.session.context, connector_no_export=True)
        openerp_id = self.model.create(self.session.cr,
                                       self.session.uid,
                                       data,
                                       context=context)
        _logger.debug('%s %d created from magento %s',
                      self.model._name, openerp_id, self.magento_id)
        return openerp_id

    def _update(self, openerp_id, data):
        """ Update an OpenERP record """
        context = dict(self.session.context, connector_no_export=True)
        self.model.write(self.session.cr,
                         self.session.uid,
                         openerp_id,
                         data,
                         context=context)
        _logger.debug('%s %d updated from magento %s',
                      self.model._name, openerp_id, self.magento_id)
        return

    def _after_import(self, openerp_id):
        """ Hook called at the end of the import """
        return

    def run(self, magento_id):
        """ Run the synchronization

        :param magento_id: identifier of the record on Magento
        """
        self.magento_id = magento_id
        self.magento_record = self._get_magento_data()

        if self._has_to_skip():
            return

        # import the missing linked resources
        self._import_dependencies()

        record = self._map_data()

        # special check on data before import
        self._validate_data(record)

        openerp_id = self.binder.to_openerp(self.magento_id)

        if openerp_id:
            self._update(openerp_id, record)
        else:
            openerp_id = self._create(record)

        self.binder.bind(self.magento_id, openerp_id)

        self._after_import(openerp_id)


class BatchImportSynchronizer(connector.ImportSynchronizer):
    """ The role of a BatchImportSynchronizer is to search for a list of
    items to import, then it can either import them directly or delay
    the import of each item separately.
    """

    def run(self, filters=None):
        """ Run the synchronization """
        record_ids = self.backend_adapter.search(filters)
        for record_id in record_ids:
            self._import_record(record_id)

    def _import_record(self, record):
        """ Import a record directly or delay the import of the record """
        raise NotImplementedError


# imported after base classes to avoid circular imports
from ..queue import job


@magento
class DirectBatchImport(BatchImportSynchronizer):
    """ Import the Magento Websites, Stores, Storeviews

    They are imported directly because this is a rare and fast operation,
    performed from the UI.
    """
    _model_name = [
            'magento.website',
            'magento.store',
            'magento.storeview',
            ]

    def _import_record(self, record):
        """ Import the record directly """
        job.import_record(self.session,
                          self.model._name,
                          self.backend_record.id,
                          record)


@magento
class DelayedBatchImport(BatchImportSynchronizer):
    """ Delay import of the records """
    _model_name = [
            'magento.res.partner.category',
            ]

    def _import_record(self, record):
        """ Delay the import of the records"""
        job.import_record.delay(self.session,
                                self.model._name,
                                self.backend_record.id,
                                record)


@magento
class SimpleRecordImport(MagentoImportSynchronizer):
    """ Import one Magento Website """
    _model_name = [
            'magento.website',
            'magento.store',
            'magento.storeview',
            'magento.res.partner.category',
        ]


@magento
class PartnerBatchImport(BatchImportSynchronizer):
    """ Import the Magento Partners.

    For every partner in the list, a delayed job is created.
    """
    _model_name = ['magento.res.partner']

    def _import_record(self, record):
        """ Delay a job for the import """
        job.import_record.delay(self.session,
                                self.model._name,
                                self.backend_record.id,
                                record)

    def run(self, filters=None):
        """ Run the synchronization """
        record_ids = self.backend_adapter.search(filters)
        for record_id in record_ids:
            self._import_record(record_id)


@magento
class PartnerImport(MagentoImportSynchronizer):
    _model_name = ['magento.res.partner']

    def _import_dependencies(self):
        """ Import the dependencies for the record"""
        record = self.magento_record

        # import customer groups
        env = connector.Environment(self.backend_record,
                                    self.session,
                                    'magento.res.partner.category')
        binder = env.get_connector_unit(connector.Binder)
        if binder.to_openerp(record['group_id']) is None:
            importer = env.get_connector_unit(MagentoImportSynchronizer)
            importer.run(record['group_id'])

    def _after_import(self, openerp_id):
        """ Import the addresses """
        env = connector.Environment(self.backend_record,
                                    self.session,
                                    'magento.address')
        addresses_adapter = env.get_connector_unit(connector.BackendAdapter)
        mag_address_ids = addresses_adapter.search(
                {'customer_id': {'eq': self.magento_id}})
        if mag_address_ids:
            importer = env.get_connector_unit(MagentoImportSynchronizer)
            partner_row = self.model.read(self.session.cr,
                                         self.session.uid,
                                         openerp_id,
                                         ['openerp_id'],
                                         context=self.session.context)
            for address_id in mag_address_ids:
                importer.run(address_id, partner_row['openerp_id'][0])


@magento
class AddressImport(MagentoImportSynchronizer):
    _model_name = ['magento.address']

    def run(self, magento_id, partner_id):
        """ Run the synchronization """
        self.partner_id = partner_id
        super(AddressImport, self).run(magento_id)

    def _create(self, data):
        """ Create the OpenERP record """
        data['parent_id'] = self.partner_id
        return super(AddressImport, self)._create(data)

    def _update(self, openerp_id, data):
        """ Update an OpenERP record """
        data['parent_id'] = self.partner_id
        return super(AddressImport, self)._update(openerp_id, data)


@magento
class ProductCategoryBatchImport(BatchImportSynchronizer):
    """ Import the Magento Product Categories.

    For every partner in the list, a delayed job is created.
    """
    _model_name = ['magento.product.category']

    def _import_record(self, magento_id, priority=None):
        """ Delay a job for the import """
        job.import_record.delay(self.session,
                                self.model._name,
                                self.backend_record.id,
                                magento_id,
                                priority=priority)

    def run(self, filters=None):
        """ Run the synchronization """
        assert not filters, "filters are not used for product categories"
        base_priority = 10
        def import_nodes(tree, level=0):
            for node_id, children in tree.iteritems():
                # By changing the priority, the top level category has
                # more chance to be imported before the childrens.
                # However, importers have to ensure that their parent is
                # there and import it if it doesn't exist
                self._import_record(node_id, priority=base_priority+level)
                import_nodes(children, level=level+1)
        tree = self.backend_adapter.tree()
        import_nodes(tree)


@magento
class ProductCategoryImport(MagentoImportSynchronizer):
    _model_name = ['magento.product.category']

    def _import_dependencies(self):
        """ Import the dependencies for the record"""
        record = self.magento_record
        env = self.environment

        # import parent category
        # the root category has a 0 parent_id
        if record.get('parent_id'):
            binder = env.get_connector_unit(connector.Binder)
            if binder.to_openerp(record['parent_id']) is None:
                importer = env.get_connector_unit(MagentoImportSynchronizer)
                importer.run(record['parent_id'])
