import cv2
import matplotlib.pyplot as plt

img = cv2.imread("1.jpg")
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
plt.figure(figsize=(10, 8))
plt.imshow(img_rgb)
plt.title("Image: 1.jpg")
plt.axis("off")
plt.show()
print(f"Image shape: {img.shape}")
print(f"Image dtype: {img.dtype}")
