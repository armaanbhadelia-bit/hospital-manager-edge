"""A status improvement is logged, but does not request another acknowledgement."""


def needs_ack(event):
    return event['kind'] == 'CRITICAL' or (
        event['kind'] == 'ELEVATED' and event['old_status'] != 'CRITICAL'
    )


# Keep the database count consistent with the UI and acknowledgement endpoint.
ACK_SQL = "(e.kind='CRITICAL' OR (e.kind='ELEVATED' AND COALESCE(e.old_status,'') <> 'CRITICAL'))"
