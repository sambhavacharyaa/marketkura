def notification_counts(request):
    if request.user.is_authenticated:
        return {
            'unread_notification_count': request.user.notifications.filter(is_read=False).count(),
            'recent_notifications': request.user.notifications.select_related('actor')[:5],
        }
    return {'unread_notification_count': 0, 'recent_notifications': []}
