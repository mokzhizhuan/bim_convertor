import PySimpleGUI as sg
import cv2

layout = [
	[sg.Image(key = '-IMAGE-')],
	[sg.Text('Person in Picture: 0', key = '-TEXT-', expand_x = True, justification = 'c')]
]

window = sg.Window('Face Detector', layout)

# Camera Feed #
video = cv2.VideoCapture(0)
face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')

while True:
	event, values = window.read(timeout = 0)
	if event == sg.WIN_CLOSED:
		break

	_, frame = video.read()
	gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
	faces = face_cascade.detectMultiScale(
		gray,
		scaleFactor = 1.3, 
		minNeighbors = 7,
		minSize =(30,30))

	# Rectangle #
	for (x, y, w, h) in faces:
		cv2.rectangle(frame,(x,y),(x + w, y + h),(0,255,0),2)

	# Image Updates #
	imgbytes = cv2.imencode('.png',frame)[1].tobytes()
	window['-IMAGE-'].update(data = imgbytes)

	# Text Updates #
	window['-TEXT-'].update(f'Persons in Picture: {len(faces)}')

window.close()