# Nelson Dane
# API to Interface with Selenium

from time import sleep

from selenium import webdriver
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager


def type_slowly(element, string, delay=0.3):
    """
    Type a string into an element, one character at a time
    :param element:
    Selenium WebElement instance
    :param string:
    String to type
    :param delay:
    Delay between each character
    :return:
    """
    for character in string:
        element.send_keys(character)
        sleep(delay)


def check_if_page_loaded(driver):
    """
    Check if the page is loaded through document.readyState
    :param driver:
    Selenium WebDriver instance
    :return:
    """
    readystate = driver.execute_script("return document.readyState;")
    return readystate == "complete"


def getDriver(DOCKER=False):
    # Init webdriver options
    options = webdriver.EdgeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    if DOCKER:
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
    # Init webdriver
    driver = webdriver.Edge(
        service=Service(EdgeChromiumDriverManager(cache_valid_range=30).install()),
        options=options,
    )
    driver.maximize_window()
    return driver


def killDriver(drivers):
    for driver in drivers:
        print(f"Killed Selenium driver {drivers.index(driver) + 1}")
        driver.close()
        driver.quit()
