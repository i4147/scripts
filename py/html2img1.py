from selenium import webdriver
from PIL import Image
import io

driver = webdriver.Chrome()
driver.get(url)
screenshot = driver.get_screenshot_as_png()
image = Image.open(io.BytesIO(screenshot))
image.save("output.png")
driver.quit()
