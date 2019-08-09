from datetime import date
from unittest import mock
import pytest
from allocation import commands, exceptions, messagebus, repository, unit_of_work


class FakeRepository(repository.AbstractRepository):

    def __init__(self, products):
        super().__init__()
        self._products = set(products)

    def _add(self, product):
        self._products.add(product)

    def _get(self, sku):
        return next((p for p in self._products if p.sku == sku), None)

    def _get_by_batchid(self, batchid):
        return next((
            p for p in self._products for b in p.batches
            if b.reference == batchid
        ), None)


class FakeUnitOfWork(unit_of_work.AbstractUnitOfWork):

    def __init__(self):
        self.init_repositories(FakeRepository([]))
        self.committed = False

    def _commit(self):
        self.committed = True

    def rollback(self):
        pass



class FakeBus(messagebus.MessageBus):
    def __init__(self):
        super().__init__(
            uow=FakeUnitOfWork(),
            send_mail=mock.Mock(),
            publish=mock.Mock(),
        )



class TestAddBatch:

    @staticmethod
    def test_for_new_product():
        bus = FakeBus()
        bus.handle([commands.CreateBatch('b1', 'sku1', 100, None)])
        assert bus.uow.products.get('sku1') is not None
        assert bus.uow.committed

    @staticmethod
    def test_for_existing_product():
        bus = FakeBus()
        bus.handle([
            commands.CreateBatch('b1', 'sku1', 100, None),
            commands.CreateBatch('b2', 'sku1', 99, None),
        ])
        assert 'b2' in [b.reference for b in bus.uow.products.get('sku1').batches]


class TestAllocate:

    @staticmethod
    def test_allocates():
        bus = FakeBus()
        bus.handle([
            commands.CreateBatch('b1', 'sku1', 100, None),
            commands.Allocate('o1', 'sku1', 10),
        ])
        [batch] = bus.uow.products.get('sku1').batches
        assert batch.available_quantity == 90

    @staticmethod
    def test_errors_for_invalid_sku():
        bus = FakeBus()
        bus.handle([commands.CreateBatch('b1', 'actualsku', 100, None)])

        with pytest.raises(exceptions.InvalidSku) as ex:
            bus.handle([
                commands.Allocate('o1', 'nonexistentsku', 10)
            ])
        assert 'Invalid sku nonexistentsku' in str(ex)

    @staticmethod
    def test_commits():
        bus = FakeBus()
        bus.handle([
            commands.CreateBatch('b1', 'sku1', 100, None),
            commands.Allocate('o1', 'sku1', 10),
        ])
        assert bus.uow.committed

    @staticmethod
    def test_sends_email_on_out_of_stock_error():
        bus = FakeBus()
        bus.handle([
            commands.CreateBatch('b1', 'sku1', 9, None),
            commands.Allocate('o1', 'sku1', 10),
        ])
        assert bus.dependencies['send_mail'].call_args == mock.call(
            'stock@made.com',
            f'Out of stock for sku1',
        )


class TestChangeBatchQuantity:

    @staticmethod
    def test_changes_available_quantity():
        bus = FakeBus()
        bus.handle([commands.CreateBatch('b1', 'sku1', 100, None)])
        [batch] = bus.uow.products.get(sku='sku1').batches
        assert batch.available_quantity == 100

        bus.handle([commands.ChangeBatchQuantity('b1', 50)])
        assert batch.available_quantity == 50


    @staticmethod
    def test_reallocates_if_necessary():
        bus = FakeBus()
        bus.handle([
            commands.CreateBatch('b1', 'sku1', 50, None),
            commands.CreateBatch('b2', 'sku1', 50, date.today()),
            commands.Allocate('o1', 'sku1', 20),
            commands.Allocate('o2', 'sku1', 20),
        ])
        [batch1, batch2] = bus.uow.products.get(sku='sku1').batches
        assert batch1.available_quantity == 10

        bus.handle([commands.ChangeBatchQuantity('b1', 25)])

        # o1 or o2 will be deallocated, so we'll have 25 - 20 * 1
        assert batch1.available_quantity == 5
        # and 20 will be reallocated to the next batch
        assert batch2.available_quantity == 30

