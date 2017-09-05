import pytest

from ethereum import utils, vm
from ethereum.exceptions import InvalidTransaction
from ethereum.slogging import configure_logging
from ethereum.transactions import Transaction

from sharding.tools import tester as t
from sharding.receipt_consuming_tx_utils import apply_shard_transaction
from sharding.used_receipt_store_utils import (get_urs_ct, get_urs_contract,
                                               mk_initiating_txs_for_urs)
from sharding.validator_manager_utils import get_valmgr_addr, get_valmgr_ct

config_string = 'sharding.rctx:debug'
configure_logging(config_string=config_string)

def mk_testing_receipt_consuming_tx(
        receipt_id, to_addr, value, data=b'', v=1, s=0):
    startgas = 300000
    tx = Transaction(0, t.GASPRICE, startgas, to_addr, value, data)
    tx.v, tx.r, tx.s = v, receipt_id, s
    return tx


@pytest.fixture
def c():
    chain = t.Chain(env='sharding', deploy_sharding_contracts=True)
    chain.mine(5)
    return chain


def test_receipt_consuming_transaction(c):
    valmgr = t.ABIContract(c, get_valmgr_ct(), get_valmgr_addr())

    to_addr = utils.privtoaddr(utils.sha3("test_to_addr"))
    data = b'123'

    # registre receipts in mainchain
    shard_id = 0
    valmgr.tx_to_shard(to_addr, shard_id, b'', sender=t.k0, value=1)
    value = 500000
    receipt_id = valmgr.tx_to_shard(
        to_addr, shard_id, data, sender=t.k0, value=value
    )

    # Setup the environment in shard `shard_id` #################
    # create the contract USED_RECEIPT_STORE in shard `shard_id`
    c.add_test_shard(shard_id)
    shard_state = c.shard_head_state[shard_id]
    c.mine(1)
    urs0 = t.ABIContract(
        c, get_urs_ct(shard_id), get_urs_contract(shard_id)['addr'],
        shard_id=shard_id
    )

    assert not urs0.get_used_receipts(receipt_id)
    c.mine(1)
    # test receipt-consuming-tx: wrong receipt_id
    rctx = mk_testing_receipt_consuming_tx(0, to_addr, value)
    with pytest.raises(InvalidTransaction):
        success, output = apply_shard_transaction(
            c.head_state, shard_state, shard_id, rctx
        )
    assert not urs0.get_used_receipts(receipt_id)
    # test receipt-consuming-tx: to_addr is not correct
    rctx = mk_testing_receipt_consuming_tx(receipt_id, t.a9, value)
    with pytest.raises(InvalidTransaction):
        success, output = apply_shard_transaction(
            c.head_state, shard_state, shard_id, rctx
        )
    assert not urs0.get_used_receipts(receipt_id)
    # test receipt-consuming-tx: value is not correct
    rctx = mk_testing_receipt_consuming_tx(receipt_id, to_addr, value - 1)
    with pytest.raises(InvalidTransaction):
        success, output = apply_shard_transaction(
            c.head_state, shard_state, shard_id, rctx
        )
    assert not urs0.get_used_receipts(receipt_id)
    # test receipt-consuming-tx: correct receipt_id
    to_addr_orig_balance = shard_state.get_balance(to_addr)
    urs0_orig_balance = shard_state.get_balance(
        get_urs_contract(shard_id)['addr']
    )
    rctx = mk_testing_receipt_consuming_tx(receipt_id, to_addr, value)
    success, output = apply_shard_transaction(
        c.head_state, shard_state, shard_id, rctx
    )
    assert success and urs0.get_used_receipts(receipt_id)
    # TODO: not sure how much the balance should increase. It still depends on
    #       whether we should deduct the tx.intrinsic gas
    assert to_addr_orig_balance < shard_state.get_balance(to_addr)
    # There shouldn't be extra money generated in the urs0
    assert shard_state.get_balance(get_urs_contract(shard_id)['addr']) == \
           urs0_orig_balance - (value - rctx.startgas * rctx.gasprice)
