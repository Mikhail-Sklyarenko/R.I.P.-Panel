"""Never route a Wingman session through the Deathmatch launcher."""


def live_unavailable_reason():
    return ("Напарники / Inferno, Nuke: автоматический поиск ещё не подключён. "
            "Для текущего тестового матча используйте кнопку «Тест Напарников — текущий матч» "
            "в настройках панели. DM не будет запущен вместо этого режима.")
