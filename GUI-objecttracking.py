import PySimpleGUI as sg
import cv2

layout = [
	[sg.Image(key = '-IMAGE-')]
]

window = sg.Window('Live Feed Object Tracker', layout)

# Camera Feed #
video = cv2.VideoCapture(0)

# Tracking Object with Bounding #
# tracker = cv2.legacy.TrackerMOSSE_create()
# tracker = cv2.legacy.TrackerCSRT_create()
tracker = cv2.legacy.TrackerMedianFlow_create()
# tracker = cv2.legacy.TrackerKCF_create()	#High Speed. Lose Object, Lose Track#
# tracker = cv2.TrackerGOTURN_create()	#Deep Learning Tracker#

_, frame = video.read()
bbox = cv2.selectROI("Tracking",frame,False)
tracker.init(frame,bbox)


def drawBox(frame, bbox):
	x, y, w, h = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
	cv2.rectangle(frame, (x,y), ((x+w), (y+h)), (255,0,255),3,1)
	cv2.putText(frame,"Tracking",(75,75),cv2.QT_FONT_NORMAL,0.7,(0,255,0),2)

while True:
	timer = cv2.getTickCount()
	event, values = window.read(timeout = 0)
	_, frame = video.read()

	success, bbox = tracker.update(frame)
	print(bbox)

	if success:
		drawBox(frame, bbox)
	else:
		cv2.putText(frame,"Tracker Lost",(75,75),cv2.QT_FONT_NORMAL,0.7,(0,0,255),2)

	fps = cv2.getTickFrequency()/(cv2.getTickCount()-timer)
	cv2.putText(frame,str(int(fps)),(75,50),cv2.QT_FONT_NORMAL,0.7,(0,255,0),2)

	if event == sg.WIN_CLOSED:
		break

	# Image Updates #
	imgbytes = cv2.imencode('.png',frame)[1].tobytes()
	window['-IMAGE-'].update(data = imgbytes)

window.close()