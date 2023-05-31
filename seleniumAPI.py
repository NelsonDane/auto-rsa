# Nelson Dane
# API to Interface with Selenium

import logging
import os
import sys
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.microsoft import EdgeChromiumDriverManager


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


def killDriver(driver):
    print("Killed Selenium driver")
    driver.close()
    driver.quit()
