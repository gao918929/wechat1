// Animated pixel sprite: a horizontal sprite sheet (/assets/px/<name>.svg) stepped frame by frame.
//   <px-sprite name="sprite-chef" frames="2" size="120" duration="700" />
Component({
  properties: {
    name: { type: String, value: '' },       // sprite sheet file name (without .svg)
    frames: { type: Number, value: 2 },      // frames laid out left → right
    size: { type: Number, value: 96 },       // frame width in rpx
    height: { type: Number, value: 0 },      // frame height in rpx (defaults to size)
    duration: { type: Number, value: 800 },  // ms per full loop
    playing: { type: Boolean, value: true }
  }
});
