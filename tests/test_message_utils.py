from swamp.message import WriteTransaction, ReadTransaction, MemReset, SWAMPMessage, sort_transactions, ensure_groups_are_atomic


def test_sort_transactions():
    # Create some transactions
    transaction_1 = WriteTransaction(10, 5, 1)
    transaction_2 = ReadTransaction(12, 1)
    transaction_3 = MemReset(1)
    transaction_4 = WriteTransaction(14, 7, 1)
    transaction_5 = ReadTransaction(16, 1)

    # Group some transactions
    SWAMPMessage.link_messages_to_group([transaction_1, transaction_2])
    SWAMPMessage.link_messages_to_group([transaction_4, transaction_5])

    # Create a list of unsorted transactions
    unsorted_transactions = [transaction_3, transaction_5,
                             transaction_1, transaction_4, transaction_2]

    # Sort transactions
    sorted_transactions = ensure_groups_are_atomic(unsorted_transactions)

    # Expected sorted transactions
    expected_sorted_transactions = [
        transaction_3, transaction_4, transaction_5, transaction_1, transaction_2]

    assert sorted_transactions == expected_sorted_transactions, "Transactions are not sorted as expected"


def test_sort_transactions_2():
    # Create some transactions
    transaction_1 = WriteTransaction(10, 5, 1)
    transaction_2 = ReadTransaction(12, 1)
    transaction_4 = WriteTransaction(14, 7, 1)
    transaction_5 = ReadTransaction(16, 1)

    # Group some transactions
    SWAMPMessage.link_messages_to_group([transaction_1, transaction_2])
    SWAMPMessage.link_messages_to_group([transaction_4, transaction_5])

    # Test case with multiple ungrouped messages
    transaction_6 = WriteTransaction(18, 9, 1)
    transaction_7 = ReadTransaction(20, 1)
    transaction_8 = MemReset(1)

    unsorted_transactions2 = [transaction_6, transaction_2,
                              transaction_7, transaction_8, transaction_1]
    sorted_transactions2 = ensure_groups_are_atomic(unsorted_transactions2)
    expected_sorted_transactions2 = [
        transaction_6, transaction_1, transaction_2, transaction_7, transaction_8]

    assert sorted_transactions2 == expected_sorted_transactions2, "Transactions are not sorted as expected with multiple ungrouped messages"
