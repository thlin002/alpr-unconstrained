
import numpy as np
import cv2
import time

from os.path import splitext

from src.label import Label
from src.utils import getWH, nms
from src.projection_utils import getRectPts, find_T_matrix


class DLabel (Label):	# inherit from class Label

	def __init__(self,cl,pts,prob):
		self.pts = pts	# define a data member called pts and assigned a patameter pts to it
		tl = np.amin(pts,1)	# amin(array, axis=1)
		br = np.amax(pts,1)
		Label.__init__(self,cl,tl,br,prob)

def save_model(model,path,verbose=0):
	path = splitext(path)[0]
	model_json = model.to_json()
	with open('%s.json' % path,'w') as json_file:
		json_file.write(model_json)
	model.save_weights('%s.h5' % path)
	if verbose: print 'Saved to %s' % path

def load_model(path,custom_objects={},verbose=0):
	from keras.models import model_from_json

	path = splitext(path)[0]
	with open('%s.json' % path,'r') as json_file:
		model_json = json_file.read()
	model = model_from_json(model_json, custom_objects=custom_objects)
	model.load_weights('%s.h5' % path)
	if verbose: print 'Loaded from %s' % path
	return model


def reconstruct(Iorig,I,Y,out_size,threshold=.9):

	net_stride 	= 2**4	# four 2*2 max pooling layers
	# Scaling: the LP is scaled so its width matches a value between 40px and 208px
	side 		= ((208. + 40.)/2.)/net_stride
	# 7.75 , which is the mean point between the maximum and minimum LP dimensions in the augmented training data divided by the network stride.

	# the first two values of Y are the object/non-object probabilities
	Probs = Y[...,0]	#  […, 0] = [:, :, :, 0]
	# the last six values of Y are used to build the local affine transformation T_mn
	Affines = Y[...,2:]

	rx,ry = Y.shape[:2]
	ywh = Y.shape[1::-1]
	iwh = np.array(I.shape[1::-1],dtype=float).reshape((2,1))

	xx,yy = np.where(Probs>threshold)

	WH = getWH(I.shape)
	MN = WH/net_stride	# width & height in feature map

	vxx = vyy = 0.5 #alpha

	base = lambda vx,vy: np.matrix([[-vx,-vy,1.],[vx,-vy,1.],[vx,vy,1.],[-vx,vy,1.]]).T
	labels = []

	for i in range(len(xx)):
		y,x = xx[i],yy[i]
		affine = Affines[y,x]
		prob = Probs[y,x]

		mn = np.array([float(x) + .5,float(y) + .5])	# The center of the pixel for each point cell (m, n) in the feature map

		A = np.reshape(affine,(2,3))	# Affine Matrix
		A[0,0] = max(A[0,0],0.)
		A[1,1] = max(A[1,1],0.)

		pts = np.array(A*base(vxx,vyy)) #*alpha	# pts => some kind of points
		pts_MN_center_mn = pts*side
		pts_MN = pts_MN_center_mn + mn.reshape((2,1))	# a point affine transformed with respect to the orgin and then moved to (m, n) (?

		pts_prop = pts_MN/MN.reshape((2,1)) # MN is the width and height of the pic in feature map

		labels.append(DLabel(0,pts_prop,prob))	# labels with transformed point

	final_labels = nms(labels,.1)	# Non Maximum Suppression
	# Non Maximum Suppression is a computer vision method that selects a single entity out of many overlapping entities
	# (for example bounding boxes in object detection).
	# The criteria is usually discarding entities that are below a given probability bound.

	TLps = []

	if len(final_labels):
		final_labels.sort(key=lambda x: x.prob(), reverse=True)
		for i,label in enumerate(final_labels):

			t_ptsh 	= getRectPts(0,0,out_size[0],out_size[1])
			ptsh 	= np.concatenate((label.pts*getWH(Iorig.shape).reshape((2,1)),np.ones((1,4))))	# ?? concatenate of different shape ??
			H 		= find_T_matrix(ptsh,t_ptsh)
			Ilp 	= cv2.warpPerspective(Iorig,H,out_size,borderValue=.0)	# Applies a perspective transformation to an image.

			TLps.append(Ilp)

	return final_labels,TLps	# final_label: array of [cl, tl, br, prob], TLps: array of image of license plate transformed


def detect_lp(model,I,max_dim,net_step,out_size,threshold):

	min_dim_img = min(I.shape[:2])
	factor 		= float(max_dim)/min_dim_img

	w,h = (np.array(I.shape[1::-1],dtype=float)*factor).astype(int).tolist()
	w += (w%net_step!=0)*(net_step - w%net_step)
	h += (h%net_step!=0)*(net_step - h%net_step)
	Iresized = cv2.resize(I,(w,h))

	T = Iresized.copy()
	T = T.reshape((1,T.shape[0],T.shape[1],T.shape[2]))

	start 	= time.time()
	Yr 		= model.predict(T)
	Yr 		= np.squeeze(Yr)
	elapsed = time.time() - start

	L,TLps = reconstruct(I,Iresized,Yr,out_size,threshold)

	return L,TLps,elapsed	# L: array of [cl, tl, br, prob], TLps: array of image of license plate transformed
